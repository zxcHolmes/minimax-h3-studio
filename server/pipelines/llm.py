"""LLM batch pipeline: one job = a JSONL file of chat requests, run concurrently against the owned Strata server."""

import concurrent.futures as cf
import json
import threading
import time

from engine_errors import Canceled

ATTEMPTS = 3


def read_requests(path):
    """[(id, body)] from JSONL lines {"id": ..., "body": {OpenAI chat completion body}}."""
    items = []
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            items.append((str(row["id"]), row["body"]))
    return items


def run_one(runtime, body, check):
    """Retry transport errors, truncated answers and unparsable structured output; never raise."""
    wants_json = (body.get("response_format") or {}).get("type") in ("json_schema", "json_object")
    start, error = time.perf_counter(), None
    for attempt in range(1, ATTEMPTS + 1):
        check()
        try:
            reply = runtime.chat(body)
            choice = reply["choices"][0]
            content = choice["message"].get("content") or ""
            if choice.get("finish_reason") == "length":
                raise ValueError("the answer hit max_tokens")
            if wants_json:
                json.loads(content)
            return {"ok": True, "content": content, "usage": reply.get("usage") or {}, "attempts": attempt,
                    "seconds": round(time.perf_counter() - start, 2)}
        except Canceled:
            raise
        except Exception as exc:  # noqa: BLE001 - recorded per request
            error = f"{type(exc).__name__}: {exc}"[:2000]
    return {"ok": False, "error": error, "attempts": ATTEMPTS, "seconds": round(time.perf_counter() - start, 2)}


def batch(engine, *, requests_path, output_path, concurrency, on_progress):
    runtime = engine.llm
    if runtime is None:
        raise RuntimeError("Strata is not configured")
    start = time.perf_counter()
    items = read_requests(requests_path)
    on_progress("loading", 0.0)
    runtime.start(engine._check)
    load_seconds = time.perf_counter() - start
    on_progress("generating", 0.0)
    lock, done, failed, tokens = threading.Lock(), 0, 0, 0
    part = output_path.with_suffix(".part")
    with part.open("w") as out, cf.ThreadPoolExecutor(concurrency) as pool:
        futures = {pool.submit(run_one, runtime, body, engine._check): key for key, body in items}
        try:
            for future in cf.as_completed(futures):
                row = {"id": futures[future], **future.result()}
                with lock:
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
                    out.flush()
                    done += 1
                    failed += not row["ok"]
                    tokens += row.get("usage", {}).get("completion_tokens", 0)
                on_progress("generating", done / len(items))
        except Canceled:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
    engine._check()
    part.replace(output_path)
    seconds = time.perf_counter() - start - load_seconds
    return {
        "output": output_path.name,
        "requests": len(items),
        "succeeded": done - failed,
        "failed": failed,
        "completion_tokens": tokens,
        "tokens_per_second": round(tokens / seconds, 1) if seconds > 0 else None,
        "models": llm_model_info(runtime),
        "timings": {"load": round(load_seconds, 1), "generate": round(seconds, 1)},
    }


def llm_model_info(runtime):
    return {"id": "llm", "label": runtime.model, "runtime": "strata", "parallel": runtime.parallel}
