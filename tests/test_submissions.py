"""Submissions regression tests."""

from api_support import APIAppTestCase
from aiohttp import FormData
from PIL import Image
import io


class SubmissionsTests(APIAppTestCase):
    async def test_create_roundtrip_and_queue(self):
        response = await self.client.post(
            "/api/jobs", data=self.form(seed=42, remove_background="false")
        )
        self.assertEqual(response.status, 201)
        job = await response.json()
        self.assertEqual(job["mode"], "i23d")
        self.assertEqual((job["width"], job["height"]), (48, 64))
        self.assertEqual(job["seed"], 42)
        self.assertEqual(
            job["mesh_options"],
            {"resolution": 1024, "texture_size": 2048, "remove_background": False},
        )
        self.assertEqual(self.worker.queue.get_nowait(), job["id"])
        self.assertTrue((self.settings.uploads / job["image"]).is_file())
        self.assertEqual(job["model_3d_url"], None)
        self.store.update(
            job["id"],
            status="done",
            model_3d="test.glb",
            result={"models": {"unet": "recorded"}},
        )
        jobs = await (await self.client.get("/api/jobs")).json()
        self.assertEqual(jobs[0]["model_3d_url"], "/files/models3d/test.glb")
        self.assertEqual(jobs[0]["models"]["unet"], "recorded")

    async def test_invalid_input_does_not_queue(self):
        for form in (
            self.form(image=False),
            self.form(mesh_resolution=2048),
            self.form(texture_size=99),
            self.form(remove_background="maybe"),
            self.form(mesh_resolution="nan"),
        ):
            response = await self.client.post("/api/jobs", data=form)
            self.assertEqual(response.status, 400, await response.text())
        self.assertEqual(self.store.count(), 0)
        self.assertTrue(self.worker.queue.empty())

    async def test_existing_video_and_picture(self):
        for fields, mode in (
            ({"prompt": "A red panda", "resolution": "544p"}, "t2v"),
            ({"kind": "image", "prompt": "A zebra", "aspect_ratio": "1:1"}, "t2i"),
        ):
            response = await self.client.post("/api/jobs", data=fields)
            self.assertEqual(response.status, 201, await response.text())
            job = await response.json()
            self.assertEqual(job["mode"], mode)
            self.assertIsNone(job["mesh_options"])

    async def test_frame_reference_and_music_forms(self):
        def png_form(**fields):
            form = FormData()
            for key, value in fields.items():
                if key in ("image", "last_image", "ref_image"):
                    png = io.BytesIO()
                    Image.new("RGB", (48, 64)).save(png, format="PNG")
                    form.add_field(
                        key,
                        png.getvalue(),
                        filename=key + ".png",
                        content_type="image/png",
                    )
                else:
                    form.add_field(key, str(value))
            return form

        cases = (
            ({"prompt": "Animate this", "image": True}, "i2v"),
            ({"prompt": "Between frames", "image": True, "last_image": True}, "fl2v"),
            ({"prompt": "A reference", "ref_image": True}, "r2v"),
            (
                {
                    "kind": "music",
                    "prompt": "Acoustic guitar",
                    "lyrics": "[Instrumental]",
                },
                "t2m",
            ),
        )
        for fields, mode in cases:
            response = await self.client.post("/api/jobs", data=png_form(**fields))
            self.assertEqual(response.status, 201, await response.text())
            job = await response.json()
            self.assertEqual(job["mode"], mode)
            if mode in ("i2v", "fl2v"):
                self.assertIn("<Picture 1>", job["prompt"])
            if mode == "fl2v":
                self.assertIn("<Picture 2>", job["prompt"])
            if mode == "r2v":
                self.assertEqual(job["lora"], "fasth3-omniref")
        response = await self.client.post(
            "/api/jobs", data=png_form(prompt="Invalid", last_image=True)
        )
        self.assertEqual(response.status, 400)
