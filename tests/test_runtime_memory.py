"""VRAM admission/residency and recovery, without allocating GPU tensors."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from api_support import APIAppTestCase
from engine_errors import MemoryPressure
from job_worker import Worker
from runtime_memory import MemoryPolicy, is_memory_error

GIB = 1024**3


def policy(free=8 * GIB):
    mm = SimpleNamespace(
        get_torch_device=Mock(return_value=SimpleNamespace(type="cuda")),
        get_free_memory=Mock(return_value=free),
        get_total_memory=Mock(return_value=24 * GIB),
        minimum_inference_memory=Mock(return_value=GIB),
        free_memory=Mock(),
        unload_all_models=Mock(),
        soft_empty_cache=Mock(),
    )
    engine = SimpleNamespace(mm=mm, _after_node=Mock(), unload=Mock())
    return MemoryPolicy(engine), mm


class MemoryPolicyTests(unittest.TestCase):
    def test_same_model_and_healthy_managed_switch_keep_models(self):
        memory, mm = policy()
        for task in [("image", "klein"), ("image", "klein"), ("music",)]:
            memory.prepare(task)
            self.assertEqual(memory.status["action"], "retained")
        mm.free_memory.assert_not_called()
        mm.unload_all_models.assert_not_called()
        mm.soft_empty_cache.assert_not_called()

    def test_pressure_frees_only_required_memory(self):
        memory, mm = policy()
        mm.get_free_memory.side_effect = [GIB // 2, 2 * GIB, 2 * GIB, 2 * GIB]
        memory.prepare(("image", "klein"))
        mm.free_memory.assert_called_once()
        self.assertEqual(mm.free_memory.call_args.args[0], GIB)
        mm.unload_all_models.assert_not_called()
        self.assertEqual(memory.status["action"], "reclaimed")

    def test_external_runtime_offloads_only_on_entry(self):
        memory, mm = policy()
        memory.prepare(("flashvsr",))
        mm.unload_all_models.assert_called_once()
        memory.prepare(("flashvsr",))
        mm.unload_all_models.assert_called_once()
        self.assertEqual(memory.status["action"], "retained")

    def test_pressure_stops_before_loading_when_reclaim_cannot_help(self):
        memory, mm = policy(free=GIB // 4)
        with self.assertRaisesRegex(MemoryPressure, "Task stopped before loading"):
            memory.prepare(("music",))
        mm.free_memory.assert_called_once()
        mm.unload_all_models.assert_called_once()
        self.assertIsNone(memory.task)
        self.assertEqual(memory.status["action"], "blocked")

    def test_cancel_during_offload_stops_before_pipeline_setup(self):
        from h3_engine import H3Engine
        from engine_errors import Canceled

        engine = H3Engine(None, [])
        engine.mm = SimpleNamespace(interrupt_current_processing=Mock())
        engine.memory = SimpleNamespace(
            prepare=lambda task: setattr(engine, "_cancel", True)
        )
        with self.assertRaises(Canceled):
            engine._prepare_task(("image", "klein"))

    def test_oom_detection_does_not_misclassify_other_runtime_errors(self):
        self.assertTrue(
            is_memory_error(RuntimeError("CUDA out of memory. Tried to allocate"))
        )
        self.assertTrue(is_memory_error(MemoryPressure("low")))
        self.assertFalse(is_memory_error(RuntimeError("CUDA illegal memory access")))
        self.assertFalse(is_memory_error(ValueError("invalid model")))


class WorkerMemoryTests(APIAppTestCase):
    async def test_oom_marks_failed_releases_traceback_then_allows_next_job(self):
        seen = []
        memory = SimpleNamespace(observe=Mock(), recover=Mock())

        def generate(**kwargs):
            seen.append(kwargs["prompt"])
            if len(seen) == 1:
                raise RuntimeError("CUDA out of memory")
            return {"steps": 4}

        engine = SimpleNamespace(generate_image=generate, memory=memory)
        worker = Worker(self.store, engine, self.settings)
        worker.state = "ready"
        for prompt in ["first", "second"]:
            job = self.store.create(mode="t2i", prompt=prompt, refs=[])
            worker._run_one(job["id"])
            result = self.store.get(job["id"])
            self.assertEqual(
                result["status"], "failed" if prompt == "first" else "done"
            )
            if prompt == "first":
                self.assertIn("cached models released", result["error"])
        memory.recover.assert_called_once()
        self.assertEqual(worker.state, "ready")
        self.assertIsNone(worker.running_id)

    async def test_failed_recovery_stops_inference(self):
        memory = SimpleNamespace(
            observe=Mock(),
            recover=Mock(side_effect=RuntimeError("CUDA context unusable")),
        )
        engine = SimpleNamespace(
            generate_image=Mock(side_effect=RuntimeError("CUDA out of memory")),
            memory=memory,
        )
        worker = Worker(self.store, engine, self.settings)
        worker.state = "ready"
        job = self.store.create(mode="t2i", prompt="test", refs=[])
        worker._run_one(job["id"])
        self.assertEqual(worker.state, "error")
        self.assertIn("restart", self.store.get(job["id"])["error"])

    async def test_worker_leaves_queued_jobs_untouched_after_failed_recovery(self):
        memory = SimpleNamespace(
            observe=Mock(), recover=Mock(side_effect=RuntimeError("unusable GPU"))
        )
        engine = SimpleNamespace(
            load=Mock(),
            generate_image=Mock(side_effect=RuntimeError("CUDA out of memory")),
            memory=memory,
        )
        worker = Worker(self.store, engine, self.settings)
        first = self.store.create(mode="t2i", prompt="first", refs=[])
        second = self.store.create(mode="t2i", prompt="second", refs=[])
        worker.run()
        self.assertEqual(worker.state, "error")
        self.assertEqual(self.store.get(first["id"])["status"], "failed")
        self.assertEqual(self.store.get(second["id"])["status"], "queued")
        engine.generate_image.assert_called_once()
