"""Image generation/edit validation, model capabilities and reference upload persistence."""

from aiohttp import web
from model_catalog import ASPECT_RATIOS
from image_models import IMAGE_MODELS, picture_size
from job_uploads import read_image, save_upload


def image_fields(form, common, settings):
    choice = form.get("image_model") or "moss"
    if choice not in IMAGE_MODELS:
        raise ValueError(f"unknown image model {choice}")
    p = IMAGE_MODELS[choice]
    if any(
        isinstance(form.get(key), web.FileField)
        for key in ("last_image", "ref_video", "audio")
    ):
        raise ValueError(
            "image jobs accept input images, not video, audio or last frames"
        )
    uploads = []
    if isinstance(form.get("image"), web.FileField):
        uploads.append(read_image("image", form.get("image")))
    uploads += [
        read_image("ref_image", u)
        for u in form.getall("ref_image", [])
        if isinstance(u, web.FileField)
    ]
    if len(uploads) > p["max_refs"]:
        if not p["max_refs"]:
            raise ValueError(
                "MOSS-Image supports generation only; choose Klein or Qwen for editing"
            )
        raise ValueError(f"at most {p['max_refs']} input images")
    aspect = form.get("aspect_ratio") or ("image" if uploads else "1:1")
    if aspect == "image":
        if not uploads:
            raise ValueError("following an input aspect ratio requires an input image")
        w, h = uploads[0][2]
        ratio = w / h
    elif aspect in ASPECT_RATIOS:
        if uploads and choice == "qwen-image-21-turbo":
            raise ValueError(
                "Qwen editing follows the first input image; use aspect_ratio=image"
            )
        ratio = ASPECT_RATIOS[aspect]
    else:
        raise ValueError(f"unknown aspect ratio {aspect}")
    width, height = picture_size(choice, ratio)
    refs = [save_upload(upload, settings.uploads) for upload in uploads]
    return dict(
        mode="i2i" if refs else "t2i",
        image_model=choice,
        prompt=common["prompt"],
        width=width,
        height=height,
        seed=common["seed"],
        refs=refs,
    )
