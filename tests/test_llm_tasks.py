"""LLM batch API contract, per-request retries/failures and Strata VRAM handoff."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from aiohttp import FormData
from api_support import APIAppTestCase
from pipelines import llm
from test_runtime_memory import GIB, policy


def requests_form(lines, **fields):
    data = FormData()
    data.add_field("kind", "llm")
    for key, value in fields.items():
        data.add_field(key, str(value))
    body = "\n".join(json.dumps(line) for line in lines).encode()
    data.add_field("requests", body, filename="batch.jsonl", content_type="application/jsonl")
    return data


def chat(i):
    return {"id": f"r{i}", "body": {"messages": [{"role": "user", "content": f"q{i}"}]}}


class LLMAPITests(APIAppTestCase):
    async def test_batch_is_queued_with_saved_requests(self):
        response = await self.client.post("/api/jobs", data=requests_form([chat(1), chat(2)], concurrency=4))
        self.assertEqual(response.status, 201)
        job = await response.json()
        self.assertEqual(job["mode"], "llm")
        self.assertEqual(job["prompt"], "LLM batch")
        self.assertEqual(job["llm_options"], {"requests": 2, "concurrency": 4})
        self.assertEqual(len((self.settings.uploads / job["input_media"]).read_text().splitlines()), 2)
        listed = await (await self.client.get("/api/jobs?kind=llm")).json()
        self.assertEqual([j["id"] for j in listed], [job["id"]])

    async def test_rejects_bad_batches(self):
        for lines in ([], [chat(1), chat(1)], [{"id": 1, "body": {}}]):
            response = await self.client.post("/api/jobs", data=requests_form(lines))
            self.assertEqual(response.status, 400, lines)


class Runtime:
    model, parallel = "test-model", 2

    def __init__(self, replies):
        self.replies, self.start = replies, Mock()

    def chat(self, body):
        reply = self.replies[body["messages"][0]["content"]].pop(0)
        if isinstance(reply, Exception):
            raise reply
        return {"choices": [{"message": {"content": reply}, "finish_reason": "stop"}],
                "usage": {"completion_tokens": 5}}


class LLMPipelineTests(unittest.TestCase):
    def test_retries_invalid_json_and_records_failures(self):
        schema = {"type": "json_schema", "json_schema": {"name": "x", "schema": {}}}
        lines = [{"id": "a", "body": {"messages": [{"role": "user", "content": "a"}], "response_format": schema}},
                 {"id": "b", "body": {"messages": [{"role": "user", "content": "b"}]}}]
        runtime = Runtime({"a": ["{broken", '{"ok": 1}'], "b": [OSError("down")] * llm.ATTEMPTS})
        with tempfile.TemporaryDirectory() as temp:
            source, output = Path(temp) / "in.jsonl", Path(temp) / "out.jsonl"
            source.write_text("\n".join(json.dumps(line) for line in lines))
            engine = SimpleNamespace(llm=runtime, _check=lambda: None)
            result = llm.batch(engine, requests_path=source, output_path=output, concurrency=2, on_progress=Mock())
            rows = {r["id"]: r for r in map(json.loads, output.read_text().splitlines())}
        self.assertEqual((result["succeeded"], result["failed"]), (1, 1))
        self.assertEqual((rows["a"]["content"], rows["a"]["attempts"]), ('{"ok": 1}', 2))
        self.assertIn("down", rows["b"]["error"])


class LLMMemoryTests(unittest.TestCase):
    def test_strata_stops_for_other_jobs_and_audio_stops_for_strata(self):
        memory, mm = policy()
        memory.engine.llm = SimpleNamespace(running=False, stop=Mock())
        memory.engine.audio_cpp = SimpleNamespace(resident_model=None, running=True, stop=Mock(), unload=Mock())
        memory.prepare(("llm", "m"))
        memory.engine.audio_cpp.stop.assert_called_once()
        mm.unload_all_models.assert_called_once()
        # A warm Strata fills the card: the next LLM batch must not be refused for low free memory.
        memory.engine.llm.running = True
        mm.get_free_memory.return_value = GIB // 4
        memory.prepare(("llm", "m"))
        memory.engine.llm.stop.assert_not_called()
        self.assertEqual(memory.status["action"], "retained")
        mm.get_free_memory.return_value = 8 * GIB
        memory.prepare(("image", "qwen"))
        memory.engine.llm.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
