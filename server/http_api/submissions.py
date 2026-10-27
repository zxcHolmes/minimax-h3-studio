"""Shared submission validation and task-family dispatch."""

from aiohttp import web
import random
from model_catalog import MUSIC_DURATION_RANGE, RESOLUTIONS
from server_settings import DURATION_RANGE, MAX_PROMPT, MAX_SEED
from job_views import job_view, queue_positions
from .common import bad_request


from job_forms.video import video_fields
from job_forms.media import music_fields
from job_forms.picture import image_fields
from job_forms.mesh import mesh_fields

BUILDERS = {
    "video": video_fields,
    "image": image_fields,
    "music": music_fields,
    "3d": mesh_fields,
}


def common_fields(form):
    kind = form.get("kind") or "video"
    if kind not in ("video", "image", "music", "3d"):
        raise ValueError(f"unknown kind {kind}")
    prompt = (
        form.get("prompt") or ("Pixal3D image to 3D" if kind == "3d" else "")
    ).strip()
    if not prompt:
        raise ValueError("prompt is required")
    if len(prompt) > MAX_PROMPT:
        raise ValueError("prompt is too long")
    resolution = form.get("resolution") or "768p"
    if resolution not in RESOLUTIONS:
        raise ValueError(f"unknown resolution {resolution}")
    try:
        duration = float(form.get("duration") or (120 if kind == "music" else 5))
    except ValueError:
        raise ValueError("duration must be a number")
    duration_range = MUSIC_DURATION_RANGE if kind == "music" else DURATION_RANGE
    if not duration_range[0] <= duration <= duration_range[1]:
        raise ValueError(f"duration must be within {duration_range}")
    raw_seed = (form.get("seed") or "").strip()
    seed = (
        int(raw_seed) % MAX_SEED
        if raw_seed.lstrip("-").isdigit()
        else random.randrange(MAX_SEED)
    )

    if any(
        isinstance(form.get(f), web.FileField)
        for f in ("image", "last_image", "ref_image", "ref_video", "audio")
    ) and kind == "music":
        raise ValueError(f"{kind} jobs take no input images or audio")

    return kind, {
        "prompt": prompt,
        "resolution": resolution,
        "duration": duration,
        "seed": seed,
    }


async def create_job(request):
    store, worker = request.app["store"], request.app["worker"]
    form = await request.post()
    try:
        kind, common = common_fields(form)
        fields = BUILDERS[kind](form, common, request.app["settings"])
    except ValueError as exc:
        return bad_request(str(exc))
    job = store.create(**fields)
    if worker.state == "ready":
        worker.queue.put(job["id"])
    return web.json_response(job_view(job, queue_positions(store)), status=201)
