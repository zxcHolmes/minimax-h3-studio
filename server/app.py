"""MiniMax-H3 Turbo HTTP server: one resident engine, one job at a time.

Environment:
    H3_COMFYUI     ComfyUI checkout            (required)
    H3_DATA        jobs.db, videos, uploads    (default <repo>/data)
    H3_WEB_DIST    built frontend              (default <repo>/web_dist)
    H3_HOST/H3_PORT                            (default 0.0.0.0:8190)
    H3_COMFY_ARGS  extra ComfyUI CLI flags     (default triton + sage attention)
"""

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
    ASPECT_RATIOS, DEFAULT_LORAS, LEGACY_PRESETS, LORAS, MAX_REFS, RESOLUTIONS, Canceled, H3Engine, canvas_size,
    model_info, with_keyframe_prefix,
)
from h3_jobs import ACTIVE, JobStore

ROOT = Path(__file__).resolve().parent.parent
COMFYUI = Path(os.environ["H3_COMFYUI"]) if os.environ.get("H3_COMFYUI") else None
DATA = Path(os.environ.get("H3_DATA", ROOT / "data")).resolve()
WEB_DIST = Path(os.environ.get("H3_WEB_DIST", ROOT / "web_dist")).resolve()
HOST = os.environ.get("H3_HOST", "0.0.0.0")
PORT = int(os.environ.get("H3_PORT", "8190"))
COMFY_ARGS = shlex.split(os.environ.get("H3_COMFY_ARGS", "--enable-triton-backend --use-sage-attention"))

VIDEOS, THUMBS, UPLOADS = DATA / "videos", DATA / "thumbs", DATA / "uploads"
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
            self._run_one(self.queue.get())

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
            result = self.engine.generate(
                lora=job["lora"], prompt=job["prompt"], width=job["width"], height=job["height"],
                duration=job["duration"], seed=job["seed"],
                image_path=UPLOADS / job["image"] if job["image"] else None,
                last_image_path=UPLOADS / job["last_image"] if job["last_image"] else None,
                ref_paths=[UPLOADS / name for name in job["refs"]],
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
    for key, folder in (("video", "videos"), ("thumb", "thumbs"), ("image", "uploads"), ("last_image", "uploads")):
        view[f"{key}_url"] = f"/files/{folder}/{job[key]}" if job[key] else None
    view["ref_urls"] = [f"/files/uploads/{name}" for name in job["refs"]]
    # Finished jobs record what they ran on; others show what their LoRA will use.
    stored = (job["result"] or {}).get("models")
    view["models"] = stored or (model_info(job["lora"]) if job["lora"] in LORAS else None)
    return view


def queue_positions(store):
    return {job_id: i + 1 for i, job_id in enumerate(store.queued_ids())}


async def health(request):
    worker = request.app["worker"]
    return web.json_response({
        "state": worker.state, "load_error": worker.load_error, "running": worker.running_id,
        "family": worker.engine.family,
        "queued": len(request.app["store"].queued_ids()), "loaded_at": worker.loaded_at,
    })


async def presets(request):
    return web.json_response({
        "resolutions": [{"id": k, "sizes": {a: canvas_size(k, r) for a, r in ASPECT_RATIOS.items()}}
                        for k in RESOLUTIONS],
        "loras": [{"id": k, "family": v["family"], "label": v["label"], "steps": v["steps"],
                   "resolutions": v["resolutions"], "models": model_info(k)} for k, v in LORAS.items()],
        "default_loras": DEFAULT_LORAS,
        "aspect_ratios": list(ASPECT_RATIOS),
        "duration_range": DURATION_RANGE,
        "max_refs": MAX_REFS,
    })


async def list_jobs(request):
    store = request.app["store"]
    limit = min(int(request.query.get("limit", "60")), 500)
    positions = queue_positions(store)
    return web.json_response([job_view(j, positions) for j in store.list(limit)])


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
    try:
        duration = float(form.get("duration") or 5)
    except ValueError:
        return bad_request("duration must be a number")
    if not DURATION_RANGE[0] <= duration <= DURATION_RANGE[1]:
        return bad_request(f"duration must be within {DURATION_RANGE}")
    raw_seed = (form.get("seed") or "").strip()
    seed = int(raw_seed) % MAX_SEED if raw_seed.lstrip("-").isdigit() else random.randrange(MAX_SEED)

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
    if last and not first:
        return bad_request("a last frame needs a first frame")
    if refs and (first or last):
        return bad_request("send either ref_image or image / last_image, not both")
    if len(refs) > MAX_REFS:
        return bad_request(f"at most {MAX_REFS} reference images")
    # Reference images pick the ref2va DiT; everything else runs on fl2va.
    family = "ref2va" if refs else "fl2va"
    lora = form.get("lora") or DEFAULT_LORAS[family][resolution]
    if lora not in LORAS:
        return bad_request(f"unknown lora {lora}")
    if LORAS[lora]["family"] != family:
        return bad_request(f"lora {lora} is for {LORAS[lora]['family']} jobs" +
                           (", which need ref_image" if LORAS[lora]["family"] == "ref2va" else ""))
    if resolution not in LORAS[lora]["resolutions"]:
        return bad_request(f"lora {lora} supports {', '.join(LORAS[lora]['resolutions'])}")

    def save(upload):
        name = f"{os.urandom(8).hex()}{upload[1]}"
        (UPLOADS / name).write_bytes(upload[0])
        return name

    image_name = save(first) if first else None
    last_name = save(last) if last else None
    ref_names = [save(r) for r in refs]

    aspect = form.get("aspect_ratio") or "16:9"
    if aspect == "image" and (first or refs):
        w, h = (first or refs[0])[2]
        ratio = w / h
    elif aspect in ASPECT_RATIOS:
        ratio = ASPECT_RATIOS[aspect]
    else:
        return bad_request(f"unknown aspect ratio {aspect}")
    width, height = canvas_size(resolution, ratio)

    mode = "r2v" if ref_names else "fl2v" if last_name else "i2v" if image_name else "t2v"
    if image_name:
        prompt = with_keyframe_prefix(prompt, duration, last_frame=bool(last_name))
    job = store.create(mode=mode, preset=resolution, lora=lora, prompt=prompt, width=width, height=height,
                       duration=duration, seed=seed, image=image_name, last_image=last_name, refs=ref_names)
    if worker.state == "ready":
        worker.queue.put(job["id"])
    return web.json_response(job_view(job, queue_positions(store)), status=201)


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


async def delete_job(request):
    store = request.app["store"]
    job = store.get(request.match_info["id"])
    if not job:
        raise web.HTTPNotFound()
    if job["status"] in ACTIVE:
        return bad_request("cancel the job before deleting it")
    for folder, name in ((VIDEOS, job["video"]), (THUMBS, job["thumb"]), (UPLOADS, job["image"]),
                         (UPLOADS, job["last_image"]), *((UPLOADS, n) for n in job["refs"])):
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
    for folder in (DATA, VIDEOS, THUMBS, UPLOADS):
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
    app.router.add_delete("/api/jobs/{id}", delete_job)
    app.router.add_static("/files/videos", VIDEOS)
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
