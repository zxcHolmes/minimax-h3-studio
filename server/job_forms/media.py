"""Picture and music form validation."""

from server_settings import MAX_PROMPT


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
