"""Validation, metadata decoding and storage of image/video/audio uploads."""

import io
import os
from pathlib import Path
from PIL import Image
from aiohttp import web
from model_catalog import REF_VIDEO_MIN_SECONDS


def read_image(field, upload):
    """(bytes, suffix, (w, h)) for an uploaded picture, None when absent, raises ValueError if unreadable."""
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
    return (
        data,
        suffix if suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp") else ".png",
        size,
    )


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
            seconds = (
                float(container.duration / av.time_base)
                if container.duration
                else float(stream.duration * stream.time_base)
            )
    except Exception:
        raise ValueError("ref_video is not a readable video file")
    if seconds < REF_VIDEO_MIN_SECONDS:
        raise ValueError(
            f"reference videos must be at least {REF_VIDEO_MIN_SECONDS:g} s long"
        )
    suffix = Path(upload.filename or "").suffix.lower()
    return (
        data,
        suffix if suffix in (".mp4", ".mov", ".webm", ".mkv") else ".mp4",
        size,
        seconds,
    )


def read_audio(upload):
    """(bytes, suffix, seconds) for an uploaded audio file, None when absent, raises ValueError if unreadable."""
    import av

    if not isinstance(upload, web.FileField):
        return None
    data = upload.file.read()
    try:
        with av.open(io.BytesIO(data)) as container:
            stream = container.streams.audio[0]
            seconds = (
                float(container.duration / av.time_base)
                if container.duration
                else float(stream.duration * stream.time_base)
            )
    except Exception:
        raise ValueError("audio is not a readable audio file")
    suffix = Path(upload.filename or "").suffix.lower()
    return (
        data,
        suffix
        if suffix in (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus")
        else ".mp3",
        seconds,
    )


def save_upload(upload, folder):
    name = f"{os.urandom(8).hex()}{upload[1]}"
    (folder / name).write_bytes(upload[0])
    return name
