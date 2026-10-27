"""Job serialization and queue positions shared by all HTTP endpoints."""

from model_catalog import (
    LORAS,
    model_info,
    image_model_info,
    music_model_info,
    upscale_model_info,
    pixal_model_info,
)


def job_view(job, positions):
    view = dict(job)
    view["queue_position"] = positions.get(job["id"])
    for key, folder in (
        ("model_3d", "models3d"),
        ("video", "videos"),
        ("picture", "pictures"),
        ("audio", "music"),
        ("thumb", "thumbs"),
        ("image", "uploads"),
        ("last_image", "uploads"),
        ("guide_audio", "uploads"),
    ):
        view[f"{key}_url"] = f"/files/{folder}/{job[key]}" if job[key] else None
    view["ref_urls"] = [f"/files/uploads/{name}" for name in job["refs"]]
    view["ref_video_urls"] = [f"/files/uploads/{name}" for name in job["ref_videos"]]
    # Finished jobs record what they ran on; others show what their LoRA will use.
    stored = (job["result"] or {}).get("models")
    if job["mode"] == "i23d":
        view["models"] = stored or pixal_model_info()
    elif job["mode"] == "t2i":
        view["models"] = stored or image_model_info()
    elif job["mode"] == "t2m":
        view["models"] = stored or music_model_info()
    elif job["mode"] == "upscale":
        view["models"] = stored or upscale_model_info(job["upscaler"] or "seedvr2")
    else:
        view["models"] = stored or (
            model_info(job["lora"], job_strength(job), job["sampler"], job["steps"])
            if job["lora"] in LORAS
            else None
        )
    return view


def job_strength(job):
    """Jobs from before the LoRA strength option ran at full strength."""
    return 1.0 if job["lora_strength"] is None else job["lora_strength"]


def queue_positions(store):
    return {job_id: i + 1 for i, job_id in enumerate(store.queued_ids())}
