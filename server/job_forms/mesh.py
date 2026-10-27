"""Pixal3D single-image input validation and job options."""

from aiohttp import web


from job_uploads import read_image, save_upload


def mesh_fields(form, common, settings):
    prompt, seed = common["prompt"], common["seed"]
    first = read_image("image", form.get("image"))
    last = read_image("last_image", form.get("last_image"))
    refs = [
        r for u in form.getall("ref_image", []) if (r := read_image("ref_image", u))
    ]
    if not first:
        raise ValueError("3D generation requires an image")
    if (
        last
        or refs
        or any(isinstance(form.get(f), web.FileField) for f in ("ref_video", "audio"))
    ):
        raise ValueError("3D generation takes one image only")
    try:
        mesh_resolution = int(form.get("mesh_resolution") or 1024)
        texture_size = int(form.get("texture_size") or 2048)
    except ValueError:
        raise ValueError("mesh_resolution and texture_size must be integers")
    if mesh_resolution not in (1024, 1536) or texture_size not in (1024, 2048, 4096):
        raise ValueError("unsupported mesh resolution or texture size")
    remove_background = str(form.get("remove_background", "true")).lower()
    if remove_background not in ("true", "false"):
        raise ValueError("remove_background must be true or false")
    image_name = save_upload(first, settings.uploads)
    return dict(
        mode="i23d",
        prompt=prompt,
        image=image_name,
        seed=seed,
        width=first[2][0],
        height=first[2][1],
        refs=[],
        mesh_options={
            "resolution": mesh_resolution,
            "texture_size": texture_size,
            "remove_background": remove_background == "true",
        },
    )
