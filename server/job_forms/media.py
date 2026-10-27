"""Picture and music form validation."""

from model_catalog import ASPECT_RATIOS, image_size
from server_settings import MAX_PROMPT


def image_fields(form, common, settings):
    aspect = form.get("aspect_ratio") or "1:1"
    if aspect not in ASPECT_RATIOS:
        raise ValueError(f"unknown aspect ratio {aspect}")
    width, height = image_size(ASPECT_RATIOS[aspect])
    return dict(
        mode="t2i",
        prompt=common["prompt"],
        width=width,
        height=height,
        seed=common["seed"],
        refs=[],
    )


def music_fields(form, common, settings):
    lyrics = (form.get("lyrics") or "").strip()
    if len(lyrics) > MAX_PROMPT:
        raise ValueError("lyrics are too long")
    return dict(
        mode="t2m",
        prompt=common["prompt"],
        lyrics=lyrics,
        duration=common["duration"],
        seed=common["seed"],
        refs=[],
    )
