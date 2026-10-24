"""MiniMax-H3 Turbo HTTP server: one resident engine, one job at a time.

Environment:
    H3_COMFYUI     ComfyUI checkout            (required)
    H3_DATA        jobs.db, videos, pictures, music, uploads (default <repo>/data)
    H3_WEB_DIST    built frontend              (default <repo>/web_dist)
    H3_HOST/H3_PORT                            (default 0.0.0.0:8190)
    H3_COMFY_ARGS  extra ComfyUI CLI flags     (default triton + sage attention)
"""

import asyncio
import concurrent.futures
import io
import logging
import os
import queue
import random
import shlex
import threading
import time
import traceback
from pathlib import Path

from aiohttp import web

from h3_engine import (
    ASPECT_RATIOS, DEFAULT_LORAS, GROUPS, LEGACY_PRESETS, LORA_STRENGTH_RANGE, LORAS, MAX_REF_VIDEOS, MAX_REFS,
    MUSIC_DURATION_RANGE, REF_VIDEO_MIN_SECONDS,
    RESOLUTIONS, SAMPLERS, STEPS_RANGE, UPSCALE_TARGETS, UPSCALERS, Canceled, H3Engine, canvas_size, fixed_sampling,
    image_model_info, image_size, model_info, music_model_info, upscale_model_info, upscale_size, with_keyframe_prefix,
)
from h3_jobs import ACTIVE, JobStore

ROOT = Path(__file__).resolve().parent.parent
COMFYUI = Path(os.environ["H3_COMFYUI"]) if os.environ.get("H3_COMFYUI") else None
DATA = Path(os.environ.get("H3_DATA", ROOT / "data")).resolve()
WEB_DIST = Path(os.environ.get("H3_WEB_DIST", ROOT / "web_dist")).resolve()
HOST = os.environ.get("H3_HOST", "0.0.0.0")
PORT = int(os.environ.get("H3_PORT", "8190"))
COMFY_ARGS = shlex.split(os.environ.get("H3_COMFY_ARGS", "--enable-triton-backend --use-sage-attention"))

VIDEOS, PICTURES, MUSIC_DIR, THUMBS, UPLOADS = (DATA / "videos", DATA / "pictures", DATA / "music",
                                                DATA / "thumbs", DATA / "uploads")
MAX_SEED = 2 ** 48
MAX_PROMPT = 20000
DURATION_RANGE = (2.0, 15.0)

log = logging.getLogger("h3")


class Worker(threading.Thread):
    """Owns the engine; executes queued jobs strictly one at a time."""

    def __init__(self, store, engine):
        super().__init__(daemon=True, name="h3-worker")
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
        self.store.update(job_id, status="running", started_at=time.time(), stage="encoding", progress=0.0)
        last = {"t": 0.0}

        def on_progress(stage, fraction):
            now = time.monotonic()
            if fraction in (0.0, 1.0) or now - last["t"] > 0.5:
                last["t"] = now
                self.store.update(job_id, stage=stage, progress=round(fraction, 3))

        video, thumb = f"{job_id}.mp4", f"{job_id}.jpg"
        try:
            if job["mode"] == "t2i":
                picture = f"{job_id}.png"
                result = self.engine.generate_image(
                    prompt=job["prompt"], width=job["width"], height=job["height"], seed=job["seed"],
                    image_path=PICTURES / picture, thumb_path=THUMBS / thumb,
                    on_progress=on_progress)
                self.store.update(job_id, status="done", stage="done", progress=1.0, picture=picture, thumb=thumb,
                                  result=result, finished_at=time.time())
                log.info("job %s done %s", job_id, result)
                return
            if job["mode"] == "t2m":
                audio = f"{job_id}.mp3"
                result = self.engine.generate_music(
                    caption=job["prompt"], lyrics=job["lyrics"] or "", duration=job["duration"], seed=job["seed"],
                    audio_path=MUSIC_DIR / audio, on_progress=on_progress)
                self.store.update(job_id, status="done", stage="done", progress=1.0, audio=audio,
                                  result=result, finished_at=time.time())
                log.info("job %s done %s", job_id, result)
                return
            if job["mode"] == "upscale":
                source = self.store.get(job["source"])
                if not source or not source["video"] or not (VIDEOS / source["video"]).is_file():
                    raise ValueError("the source video has been deleted")
                upscale = self.engine.flashvsr_video if job["upscaler"] == "flashvsr" else self.engine.upscale_video
                result = upscale(
                    source_path=VIDEOS / source["video"], width=job["width"], height=job["height"], seed=job["seed"],
                    video_path=VIDEOS / video, thumb_path=THUMBS / thumb, on_progress=on_progress)
                self.store.update(job_id, status="done", stage="done", progress=1.0, video=video, thumb=thumb,
                                  result=result, finished_at=time.time())
                log.info("job %s done %s", job_id, result)
                return
            result = self.engine.generate(
                lora=job["lora"], prompt=job["prompt"], width=job["width"], height=job["height"],
                duration=job["duration"], seed=job["seed"], lora_strength=job_strength(job),
                sampler=job["sampler"], steps=job["steps"], image_path=UPLOADS / job["image"] if job["image"] else None,
                last_image_path=UPLOADS / job["last_image"] if job["last_image"] else None,
                ref_paths=[UPLOADS / name for name in job["refs"]],
                ref_video_paths=[UPLOADS / name for name in job["ref_videos"]],
                audio_path=UPLOADS / job["guide_audio"] if job["guide_audio"] else None,
                audio_start=job["audio_start"] or 0.0,
                video_path=VIDEOS / video, thumb_path=THUMBS / thumb, on_progress=on_progress)
            self.store.update(job_id, status="done", stage="done", progress=1.0, video=video, thumb=thumb,
                              result=result, finished_at=time.time())
            log.info("job %s done %s", job_id, result)
        except Canceled:
            self.store.update(job_id, status="canceled", finished_at=time.time())
            log.info("job %s canceled", job_id)
        except Exception:
            err = traceback.format_exc()
            self.store.update(job_id, status="failed", error=err[-4000:], finished_at=time.time())
            log.error("job %s failed:\n%s", job_id, err)
        finally:
            self.running_id = None


def job_view(job, positions):
    view = dict(job)
    view["queue_position"] = positions.get(job["id"])
    for key, folder in (("video", "videos"), ("picture", "pictures"), ("audio", "music"), ("thumb", "thumbs"),
                        ("image", "uploads"), ("last_image", "uploads"), ("guide_audio", "uploads")):
        view[f"{key}_url"] = f"/files/{folder}/{job[key]}" if job[key] else None
    view["ref_urls"] = [f"/files/uploads/{name}" for name in job["refs"]]
    view["ref_video_urls"] = [f"/files/uploads/{name}" for name in job["ref_videos"]]
    # Finished jobs record what they ran on; others show what their LoRA will use.
    stored = (job["result"] or {}).get("models")
    if job["mode"] == "t2i":
        view["models"] = stored or image_model_info()
    elif job["mode"] == "t2m":
        view["models"] = stored or music_model_info()
    elif job["mode"] == "upscale":
        view["models"] = stored or upscale_model_info(job["upscaler"] or "seedvr2")
    else:
        view["models"] = stored or (model_info(job["lora"], job_strength(job), job["sampler"], job["steps"])
                                    if job["lora"] in LORAS else None)
    return view


def job_strength(job):
    """Jobs from before the LoRA strength option ran at full strength."""
    return 1.0 if job["lora_strength"] is None else job["lora_strength"]


def queue_positions(store):
    return {job_id: i + 1 for i, job_id in enumerate(store.queued_ids())}


async def health(request):
    worker = request.app["worker"]
    return web.json_response({
        "state": worker.state, "load_error": worker.load_error, "running": worker.running_id,
        "family": worker.engine.family, "unet": worker.engine.unet,
        "queued": len(request.app["store"].queued_ids()), "loaded_at": worker.loaded_at,
    })


async def presets(request):
    return web.json_response({
        "resolutions": [{"id": k, "sizes": {a: canvas_size(k, r) for a, r in ASPECT_RATIOS.items()}}
                        for k in RESOLUTIONS],
        "groups": [{"id": k, "label": v} for k, v in GROUPS.items()],
        "loras": [{"id": k, "group": v["group"], "family": v["family"], "label": v["label"], "steps": v["steps"],
                   "fixed": fixed_sampling(k), "resolutions": v["resolutions"], "models": model_info(k)} for k, v in LORAS.items()],
        "default_loras": DEFAULT_LORAS,
        "aspect_ratios": list(ASPECT_RATIOS),
        "duration_range": DURATION_RANGE,
        "max_refs": MAX_REFS,
        "max_ref_videos": MAX_REF_VIDEOS,
        "lora_strength_range": LORA_STRENGTH_RANGE,
        "samplers": SAMPLERS,
        "steps_range": STEPS_RANGE,
        "image": {"sizes": {a: image_size(r) for a, r in ASPECT_RATIOS.items()}, "models": image_model_info()},
        "music": {"duration_range": MUSIC_DURATION_RANGE, "default_duration": 120, "models": music_model_info()},
        "upscale": {"targets": list(UPSCALE_TARGETS),
                    "upscalers": [{"id": k, "label": v["label"], "models": upscale_model_info(k)}
                                  for k, v in UPSCALERS.items()]},
    })


async def list_jobs(request):
    store = request.app["store"]
    limit = min(int(request.query.get("limit", "60")), 500)
    offset = max(int(request.query.get("offset", "0")), 0)
    positions = queue_positions(store)
    return web.json_response([job_view(j, positions) for j in store.list(limit, offset)],
                             headers={"X-Total-Count": str(store.count())})


async def get_job(request):
    store = request.app["store"]
    job = store.get(request.match_info["id"])
    if not job:
        raise web.HTTPNotFound()
    return web.json_response(job_view(job, queue_positions(store)))


def bad_request(message):
    return web.json_response({"error": message}, status=400)


async def create_job(request):
    from PIL import Image

    store, worker = request.app["store"], request.app["worker"]
    form = await request.post()

    prompt = (form.get("prompt") or "").strip()
    if not prompt:
        return bad_request("prompt is required")
    if len(prompt) > MAX_PROMPT:
        return bad_request("prompt is too long")
    resolution = form.get("resolution") or "768p"
    if resolution not in RESOLUTIONS:
        return bad_request(f"unknown resolution {resolution}")
    kind = form.get("kind") or "video"
    try:
        duration = float(form.get("duration") or (120 if kind == "music" else 5))
    except ValueError:
        return bad_request("duration must be a number")
    duration_range = MUSIC_DURATION_RANGE if kind == "music" else DURATION_RANGE
    if not duration_range[0] <= duration <= duration_range[1]:
        return bad_request(f"duration must be within {duration_range}")
    raw_seed = (form.get("seed") or "").strip()
    seed = int(raw_seed) % MAX_SEED if raw_seed.lstrip("-").isdigit() else random.randrange(MAX_SEED)

    if any(isinstance(form.get(f), web.FileField) for f in ("image", "last_image", "ref_image", "ref_video", "audio")) \
            and kind in ("image", "music"):
        return bad_request(f"{kind} jobs take no input images or audio")

    if kind == "music":
        # The prompt is the caption (style, vocals, arrangement); lyrics carry the [verse]/[chorus] structure.
        lyrics = (form.get("lyrics") or "").strip()
        if len(lyrics) > MAX_PROMPT:
            return bad_request("lyrics are too long")
        job = store.create(mode="t2m", prompt=prompt, lyrics=lyrics, duration=duration, seed=seed, refs=[])
        if worker.state == "ready":
            worker.queue.put(job["id"])
        return web.json_response(job_view(job, queue_positions(store)), status=201)

    if kind == "image":
        aspect = form.get("aspect_ratio") or "1:1"
        if aspect not in ASPECT_RATIOS:
            return bad_request(f"unknown aspect ratio {aspect}")
        width, height = image_size(ASPECT_RATIOS[aspect])
        job = store.create(mode="t2i", prompt=prompt, width=width, height=height, seed=seed, refs=[])
        if worker.state == "ready":
            worker.queue.put(job["id"])
        return web.json_response(job_view(job, queue_positions(store)), status=201)

    def read_image(field, upload=None):
        """(bytes, suffix, (w, h)) for an uploaded picture, None when absent, raises ValueError if unreadable."""
        upload = form.get(field) if upload is None else upload
        if not isinstance(upload, web.FileField):
            return None
        data = upload.file.read()
        try:
            with Image.open(io.BytesIO(data)) as img:
                img.verify()
            with Image.open(io.BytesIO(data)) as img:
                size = img.size
        except Exception:
            raise ValueError(f"{field} is not a readable picture")
        suffix = Path(upload.filename or "").suffix.lower()
        return data, suffix if suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp") else ".png", size

    try:
        first, last = read_image("image"), read_image("last_image")
        refs = [read_image("ref_image", u) for u in form.getall("ref_image", [])]
    except ValueError as e:
        return bad_request(str(e))
    refs = [r for r in refs if r]
    try:
        ref_videos = [v for v in (read_video(u) for u in form.getall("ref_video", [])) if v]
        guide = read_audio(form.get("audio"))
        audio_start = float(form.get("audio_start") or 0)
    except ValueError as e:
        return bad_request(str(e))
    if guide and not 0 <= audio_start < guide[2] - 0.5:
        return bad_request(f"audio_start must be within the audio's {guide[2]:.1f} s")
    if last and not first:
        return bad_request("a last frame needs a first frame")
    if len(refs) > MAX_REFS:
        return bad_request(f"at most {MAX_REFS} reference images")
    if len(ref_videos) > MAX_REF_VIDEOS:
        return bad_request(f"at most {MAX_REF_VIDEOS} reference videos")
    # Reference images or a ref2va model choice pick the ref2va DiT (which also runs with no references);
    # everything else runs on fl2va.
    lora = form.get("lora")
    if lora and lora not in LORAS:
        return bad_request(f"unknown lora {lora}")
    family = "ref2va" if refs or ref_videos or (lora and LORAS[lora]["family"] == "ref2va") else "fl2va"
    if family == "ref2va" and (first or last):
        return bad_request("ref2va jobs take ref_image / ref_video, not image / last_image")
    lora = lora or DEFAULT_LORAS[family][resolution]
    if LORAS[lora]["family"] != family:
        return bad_request(f"lora {lora} is for {LORAS[lora]['family']} jobs")
    if resolution not in LORAS[lora]["resolutions"]:
        return bad_request(f"lora {lora} supports {', '.join(LORAS[lora]['resolutions'])}")
    try:
        lora_strength = round(float(form.get("lora_strength") or 1.0), 2)
    except ValueError:
        return bad_request("lora_strength must be a number")
    if not LORA_STRENGTH_RANGE[0] <= lora_strength <= LORA_STRENGTH_RANGE[1]:
        return bad_request(f"lora_strength must be within {LORA_STRENGTH_RANGE}")
    if not LORAS[lora]["file"]:
        lora_strength = 1.0  # FastH3 bases have no LoRA to scale
    sampler = form.get("sampler") or None
    if sampler and sampler not in SAMPLERS:
        return bad_request(f"sampler must be one of {', '.join(SAMPLERS)}")
    if fixed_sampling(lora) or sampler == LORAS[lora].get("sampler", "euler"):
        sampler = None  # larryvrh and FastH3 keep their own sampler; the model choice's own needs no override
    try:
        steps = int(form.get("steps") or 0) or None
    except ValueError:
        return bad_request("steps must be an integer")
    if steps and not STEPS_RANGE[0] <= steps <= STEPS_RANGE[1]:
        return bad_request(f"steps must be within {STEPS_RANGE}")
    if steps == LORAS[lora]["steps"] or fixed_sampling(lora):
        steps = None

    def save(upload):
        name = f"{os.urandom(8).hex()}{upload[1]}"
        (UPLOADS / name).write_bytes(upload[0])
        return name

    image_name = save(first) if first else None
    last_name = save(last) if last else None
    ref_names = [save(r) for r in refs]
    ref_video_names = [save(v) for v in ref_videos]
    guide_name = save(guide) if guide else None

    aspect = form.get("aspect_ratio") or "16:9"
    if aspect == "image" and (first or refs or ref_videos):
        w, h = (first or (refs or ref_videos)[0])[2]
        ratio = w / h
    elif aspect in ASPECT_RATIOS:
        ratio = ASPECT_RATIOS[aspect]
    else:
        return bad_request(f"unknown aspect ratio {aspect}")
    width, height = canvas_size(resolution, ratio)

    mode = "r2v" if family == "ref2va" else "fl2v" if last_name else "i2v" if image_name else "t2v"
    if image_name:
        prompt = with_keyframe_prefix(prompt, duration, last_frame=bool(last_name))
    job = store.create(mode=mode, preset=resolution, lora=lora, lora_strength=lora_strength, sampler=sampler, steps=steps,
                       prompt=prompt, width=width, height=height, duration=duration, seed=seed, image=image_name,
                       last_image=last_name, refs=ref_names, ref_videos=ref_video_names, guide_audio=guide_name,
                       audio_start=audio_start if guide_name else None)
    if worker.state == "ready":
        worker.queue.put(job["id"])
    return web.json_response(job_view(job, queue_positions(store)), status=201)


async def upscale_job(request):
    """Queue an upscale of a finished video job; the new job keeps the source's prompt for display."""
    store, worker = request.app["store"], request.app["worker"]
    source = store.get(request.match_info["id"])
    if not source:
        raise web.HTTPNotFound()
    form = await request.post()
    target = form.get("target") or "1080p"
    if target not in UPSCALE_TARGETS:
        return bad_request(f"target must be one of {', '.join(UPSCALE_TARGETS)}")
    upscaler = form.get("upscaler") or "seedvr2"
    if upscaler not in UPSCALERS:
        return bad_request(f"upscaler must be one of {', '.join(UPSCALERS)}")
    if source["status"] != "done" or not source["video"]:
        return bad_request("only finished videos can be upscaled")
    if min(source["width"], source["height"]) >= UPSCALE_TARGETS[target]:
        return bad_request(f"the video is already {target} or larger")
    width, height = upscale_size(source["width"], source["height"], target)
    raw_seed = (form.get("seed") or "").strip()
    seed = int(raw_seed) % MAX_SEED if raw_seed.lstrip("-").isdigit() else random.randrange(MAX_SEED)
    job = store.create(mode="upscale", source=source["id"], upscaler=upscaler, preset=target, prompt=source["prompt"], width=width,
                       height=height, duration=source["duration"], seed=seed, refs=[])
    if worker.state == "ready":
        worker.queue.put(job["id"])
    return web.json_response(job_view(job, queue_positions(store)), status=201)


def read_video(upload):
    """(bytes, suffix, (w, h), seconds) for an uploaded reference video, None when absent, raises ValueError if
    unreadable or shorter than REF_VIDEO_MIN_SECONDS. Longer videos are trimmed to the job's length at run time."""
    import av
    if not isinstance(upload, web.FileField):
        return None
    data = upload.file.read()
    try:
        with av.open(io.BytesIO(data)) as container:
            stream = container.streams.video[0]
            size = (stream.codec_context.width, stream.codec_context.height)
            seconds = float(container.duration / av.time_base) if container.duration else \
                float(stream.duration * stream.time_base)
    except Exception:
        raise ValueError("ref_video is not a readable video file")
    if seconds < REF_VIDEO_MIN_SECONDS:
        raise ValueError(f"reference videos must be at least {REF_VIDEO_MIN_SECONDS:g} s long")
    suffix = Path(upload.filename or "").suffix.lower()
    return data, suffix if suffix in (".mp4", ".mov", ".webm", ".mkv") else ".mp4", size, seconds


def read_audio(upload):
    """(bytes, suffix, seconds) for an uploaded audio file, None when absent, raises ValueError if unreadable."""
    import av
    if not isinstance(upload, web.FileField):
        return None
    data = upload.file.read()
    try:
        with av.open(io.BytesIO(data)) as container:
            stream = container.streams.audio[0]
            seconds = float(container.duration / av.time_base) if container.duration else \
                float(stream.duration * stream.time_base)
    except Exception:
        raise ValueError("audio is not a readable audio file")
    suffix = Path(upload.filename or "").suffix.lower()
    return data, suffix if suffix in (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus") else ".mp3", seconds


async def cancel_job(request):
    store, worker = request.app["store"], request.app["worker"]
    job = store.get(request.match_info["id"])
    if not job:
        raise web.HTTPNotFound()
    if job["status"] == "queued":
        store.update(job["id"], status="canceled", finished_at=time.time())
    elif job["status"] == "running" and worker.running_id == job["id"]:
        worker.engine.cancel()
    return web.json_response({"ok": True})


async def unload(request):
    """Free the GPU for another program while idle; the next job reloads its models."""
    store, worker = request.app["store"], request.app["worker"]
    if worker.state != "ready":
        return web.json_response({"error": f"the engine is {worker.state}"}, status=503)
    if worker.running_id or store.queued_ids():
        return web.json_response({"error": "jobs are running or queued"}, status=409)
    result = await asyncio.wrap_future(worker.call(worker.engine.unload))
    log.info("models unloaded %s", result)
    return web.json_response(result)


async def delete_job(request):
    store = request.app["store"]
    job = store.get(request.match_info["id"])
    if not job:
        raise web.HTTPNotFound()
    if job["status"] in ACTIVE:
        return bad_request("cancel the job before deleting it")
    for folder, name in ((VIDEOS, job["video"]), (PICTURES, job["picture"]), (MUSIC_DIR, job["audio"]),
                         (THUMBS, job["thumb"]),
                         (UPLOADS, job["image"]), (UPLOADS, job["guide_audio"]),
                         (UPLOADS, job["last_image"]), *((UPLOADS, n) for n in job["refs"]),
                         *((UPLOADS, n) for n in job["ref_videos"])):
        if name:
            (folder / name).unlink(missing_ok=True)
    store.delete(job["id"])
    return web.json_response({"ok": True})


async def index(request):
    page = WEB_DIST / "index.html"
    if not page.is_file():
        return web.Response(text="frontend not deployed", status=503)
    # Read per request so a frontend-only deploy shows up without a restart.
    return web.Response(text=page.read_text(), content_type="text/html",
                        headers={"Cache-Control": "no-cache"})


def make_app():
    for folder in (DATA, VIDEOS, PICTURES, MUSIC_DIR, THUMBS, UPLOADS):
        folder.mkdir(parents=True, exist_ok=True)
    store = JobStore(DATA / "jobs.db")
    store.backfill_lora(LEGACY_PRESETS)
    store.fail_running("server restarted while the job was running")
    worker = Worker(store, H3Engine(COMFYUI, COMFY_ARGS))

    app = web.Application(client_max_size=64 * 1024 ** 2)
    app["store"], app["worker"] = store, worker
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/presets", presets)
    app.router.add_get("/api/jobs", list_jobs)
    app.router.add_post("/api/jobs", create_job)
    app.router.add_get("/api/jobs/{id}", get_job)
    app.router.add_post("/api/jobs/{id}/cancel", cancel_job)
    app.router.add_post("/api/jobs/{id}/upscale", upscale_job)
    app.router.add_post("/api/unload", unload)
    app.router.add_delete("/api/jobs/{id}", delete_job)
    app.router.add_static("/files/videos", VIDEOS)
    app.router.add_static("/files/pictures", PICTURES)
    app.router.add_static("/files/music", MUSIC_DIR)
    app.router.add_static("/files/thumbs", THUMBS)
    app.router.add_static("/files/uploads", UPLOADS)
    app.router.add_get("/{path:.*}", frontend)

    async def start_worker(_app):
        worker.start()

    app.on_startup.append(start_worker)
    return app


async def frontend(request):
    """Built frontend files, falling back to index.html for client-side routes."""
    path = request.match_info["path"]
    if path:
        target = (WEB_DIST / path).resolve()
        if target.is_relative_to(WEB_DIST) and target.is_file():
            return web.FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable"}
                                    if path.startswith("assets/") else None)
    return await index(request)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if COMFYUI is None:
        raise SystemExit("set H3_COMFYUI to the ComfyUI checkout")
    app = make_app()
    app["worker"].engine.bootstrap()
    # bootstrap() chdirs into ComfyUI; every path above is absolute.
    web.run_app(app, host=HOST, port=PORT, access_log=None)
