"""Validate an LLM batch upload: a JSONL file of {"id", "body"} chat completion requests."""

import json
import secrets

from aiohttp import web

MAX_REQUESTS = 5000


def llm_fields(form, common, settings):
    if any(isinstance(form.get(k), web.FileField) for k in ("image", "ref_image", "ref_video", "last_image", "audio")):
        raise ValueError("LLM batches take only a requests file")
    upload = form.get("requests")
    if not isinstance(upload, web.FileField):
        raise ValueError("requests (a JSONL file) is required")
    data = upload.file.read()
    ids = set()
    try:
        lines = [json.loads(line) for line in data.decode().splitlines() if line.strip()]
    except (UnicodeDecodeError, ValueError):
        raise ValueError("requests must be UTF-8 JSONL") from None
    if not 1 <= len(lines) <= MAX_REQUESTS:
        raise ValueError(f"a batch holds 1 to {MAX_REQUESTS} requests")
    for row in lines:
        if not isinstance(row, dict) or "id" not in row or not isinstance(row.get("body"), dict) \
                or not isinstance(row["body"].get("messages"), list):
            raise ValueError("each line needs an id and a body with messages")
        if str(row["id"]) in ids:
            raise ValueError(f"duplicate request id {row['id']}")
        ids.add(str(row["id"]))
    try:
        concurrency = int(form.get("concurrency") or settings.strata_concurrency)
    except ValueError:
        raise ValueError("concurrency must be an integer") from None
    if not 1 <= concurrency <= 64:
        raise ValueError("concurrency must be within 1-64")
    name = secrets.token_hex(8) + ".jsonl"
    (settings.uploads / name).write_bytes(data)
    return dict(
        mode="llm",
        prompt=common["prompt"],
        input_media=name,
        llm_options={"requests": len(lines), "concurrency": concurrency},
        seed=common["seed"],
        refs=[],
    )
