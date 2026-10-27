"""Single-threaded inference queue and engine lifecycle ownership."""

import concurrent.futures
import logging
import queue
import threading
import time
import traceback
from engine_errors import Canceled
from job_views import job_strength

log = logging.getLogger("h3")


class Worker(threading.Thread):
    """Owns the engine; executes queued jobs strictly one at a time."""

    def __init__(self, store, engine, settings):
        super().__init__(daemon=True, name="h3-worker")
        self.settings = settings
        self.store = store
        self.engine = engine
        self.queue = queue.Queue()
        self.running_id = None
        self.state = "loading"
        self.load_error = None
        self.loaded_at = None

    def run(self):
        try:
            t0 = time.perf_counter()
            self.engine.load()
            self.loaded_at = time.time()
            self.state = "ready"
            log.info("engine ready in %.1fs", time.perf_counter() - t0)
        except Exception:
            self.state = "error"
            self.load_error = traceback.format_exc()
            log.error("engine failed to load:\n%s", self.load_error)
            return
        for job_id in self.store.queued_ids():
            self.queue.put(job_id)
        while True:
            item = self.queue.get()
            if callable(item):
                item()
            else:
                self._run_one(item)

    def call(self, fn):
        """Run fn on the worker thread after the jobs queued before it; returns a concurrent Future."""
        future = concurrent.futures.Future()

        def task():
            try:
                future.set_result(fn())
            except Exception as exc:
                future.set_exception(exc)

        self.queue.put(task)
        return future

    def _run_one(self, job_id):
        job = self.store.get(job_id)
        if not job or job["status"] != "queued":
            return
        self.running_id = job_id
        self.store.update(
            job_id,
            status="running",
            started_at=time.time(),
            stage="encoding",
            progress=0.0,
        )
        last = {"t": 0.0}

        def on_progress(stage, fraction):
            now = time.monotonic()
            if fraction in (0.0, 1.0) or now - last["t"] > 0.5:
                last["t"] = now
                self.store.update(job_id, stage=stage, progress=round(fraction, 3))

        video, thumb = f"{job_id}.mp4", f"{job_id}.jpg"
        try:
            if job["mode"] == "i23d":
                model = f"{job_id}.glb"
                result = self.engine.generate_3d(
                    image_path=self.settings.uploads / job["image"],
                    model_path=self.settings.models3d / model,
                    thumb_path=self.settings.thumbs / thumb,
                    seed=job["seed"],
                    **job["mesh_options"],
                    on_progress=on_progress,
                )
                self.store.update(
                    job_id,
                    status="done",
                    stage="done",
                    progress=1.0,
                    model_3d=model,
                    thumb=thumb,
                    result=result,
                    finished_at=time.time(),
                )
                log.info("job %s done %s", job_id, result)
                return
            if job["mode"] == "t2i":
                picture = f"{job_id}.png"
                result = self.engine.generate_image(
                    prompt=job["prompt"],
                    width=job["width"],
                    height=job["height"],
                    seed=job["seed"],
                    image_path=self.settings.pictures / picture,
                    thumb_path=self.settings.thumbs / thumb,
                    on_progress=on_progress,
                )
                self.store.update(
                    job_id,
                    status="done",
                    stage="done",
                    progress=1.0,
                    picture=picture,
                    thumb=thumb,
                    result=result,
                    finished_at=time.time(),
                )
                log.info("job %s done %s", job_id, result)
                return
            if job["mode"] == "t2m":
                audio = f"{job_id}.mp3"
                result = self.engine.generate_music(
                    caption=job["prompt"],
                    lyrics=job["lyrics"] or "",
                    duration=job["duration"],
                    seed=job["seed"],
                    audio_path=self.settings.music / audio,
                    on_progress=on_progress,
                )
                self.store.update(
                    job_id,
                    status="done",
                    stage="done",
                    progress=1.0,
                    audio=audio,
                    result=result,
                    finished_at=time.time(),
                )
                log.info("job %s done %s", job_id, result)
                return
            if job["mode"] == "upscale":
                source = self.store.get(job["source"])
                if (
                    not source
                    or not source["video"]
                    or not (self.settings.videos / source["video"]).is_file()
                ):
                    raise ValueError("the source video has been deleted")
                upscale = (
                    self.engine.flashvsr_video
                    if job["upscaler"] == "flashvsr"
                    else self.engine.upscale_video
                )
                result = upscale(
                    source_path=self.settings.videos / source["video"],
                    width=job["width"],
                    height=job["height"],
                    seed=job["seed"],
                    video_path=self.settings.videos / video,
                    thumb_path=self.settings.thumbs / thumb,
                    on_progress=on_progress,
                )
                self.store.update(
                    job_id,
                    status="done",
                    stage="done",
                    progress=1.0,
                    video=video,
                    thumb=thumb,
                    result=result,
                    finished_at=time.time(),
                )
                log.info("job %s done %s", job_id, result)
                return
            result = self.engine.generate(
                lora=job["lora"],
                prompt=job["prompt"],
                width=job["width"],
                height=job["height"],
                duration=job["duration"],
                seed=job["seed"],
                lora_strength=job_strength(job),
                sampler=job["sampler"],
                steps=job["steps"],
                image_path=self.settings.uploads / job["image"]
                if job["image"]
                else None,
                last_image_path=self.settings.uploads / job["last_image"]
                if job["last_image"]
                else None,
                ref_paths=[self.settings.uploads / name for name in job["refs"]],
                ref_video_paths=[
                    self.settings.uploads / name for name in job["ref_videos"]
                ],
                audio_path=self.settings.uploads / job["guide_audio"]
                if job["guide_audio"]
                else None,
                audio_start=job["audio_start"] or 0.0,
                video_path=self.settings.videos / video,
                thumb_path=self.settings.thumbs / thumb,
                on_progress=on_progress,
            )
            self.store.update(
                job_id,
                status="done",
                stage="done",
                progress=1.0,
                video=video,
                thumb=thumb,
                result=result,
                finished_at=time.time(),
            )
            log.info("job %s done %s", job_id, result)
        except Canceled:
            self.store.update(job_id, status="canceled", finished_at=time.time())
            log.info("job %s canceled", job_id)
        except Exception:
            err = traceback.format_exc()
            self.store.update(
                job_id, status="failed", error=err[-4000:], finished_at=time.time()
            )
            log.error("job %s failed:\n%s", job_id, err)
        finally:
            self.running_id = None
