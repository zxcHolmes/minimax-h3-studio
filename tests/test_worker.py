"""Worker regression tests."""

from api_support import APIAppTestCase
from types import SimpleNamespace
from unittest.mock import Mock
from job_worker import Worker
from engine_errors import Canceled


class WorkerTests(APIAppTestCase):
    async def test_worker_dispatch(self):
        job = self.store.create(
            mode="i23d",
            prompt="object",
            image="input.png",
            seed=42,
            mesh_options={
                "resolution": 1024,
                "texture_size": 2048,
                "remove_background": True,
            },
        )
        calls = []
        engine = SimpleNamespace(
            generate_3d=lambda **kw: calls.append(kw) or {"faces": 100}
        )
        worker = Worker(self.store, engine, self.settings)
        worker._run_one(job["id"])
        result = self.store.get(job["id"])
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["model_3d"], job["id"] + ".glb")
        self.assertEqual(calls[0]["resolution"], 1024)
        self.assertIsNone(worker.running_id)

    async def test_worker_dispatches_every_pipeline_with_settings_paths(self):
        methods = (
            "generate",
            "generate_image",
            "generate_music",
            "generate_3d",
            "upscale_video",
            "flashvsr_video",
        )
        engine = SimpleNamespace(
            **{method: Mock(return_value={"test": method}) for method in methods}
        )
        worker = Worker(self.store, engine, self.settings)
        source = self.store.create(
            mode="t2v", prompt="source", video="source.mp4", width=960, height=544
        )
        (self.settings.videos / "source.mp4").write_bytes(b"fixture")
        for mode, method, result_column, folder, extra in (
            ("t2v", "generate", "video", self.settings.videos, {}),
            ("t2i", "generate_image", "picture", self.settings.pictures, {}),
            ("t2m", "generate_music", "audio", self.settings.music, {}),
            (
                "i23d",
                "generate_3d",
                "model_3d",
                self.settings.models3d,
                {
                    "mesh_options": {
                        "resolution": 1024,
                        "texture_size": 2048,
                        "remove_background": True,
                    }
                },
            ),
            (
                "upscale",
                "upscale_video",
                "video",
                self.settings.videos,
                {"source": source["id"]},
            ),
            (
                "upscale",
                "flashvsr_video",
                "video",
                self.settings.videos,
                {"source": source["id"], "upscaler": "flashvsr"},
            ),
        ):
            job = self.store.create(
                mode=mode,
                prompt="fixture",
                seed=42,
                image="input.png",
                refs=[],
                **extra,
            )
            worker._run_one(job["id"])
            result = self.store.get(job["id"])
            self.assertEqual(result["status"], "done", result["error"])
            self.assertEqual(result["result"]["test"], method)
            args = getattr(engine, method).call_args.kwargs
            path_key = {
                "video": "video_path",
                "picture": "image_path",
                "audio": "audio_path",
                "model_3d": "model_path",
            }[result_column]
            self.assertEqual(args[path_key], folder / result[result_column])
            self.assertIsNone(worker.running_id)
        engine.generate_music.side_effect = Canceled()
        job = self.store.create(mode="t2m", prompt="cancel", seed=42)
        worker._run_one(job["id"])
        self.assertEqual(self.store.get(job["id"])["status"], "canceled")
