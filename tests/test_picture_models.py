"""Image model selection, edits and legacy history compatibility."""

import io
from aiohttp import FormData
from PIL import Image
from api_support import APIAppTestCase


def picture_form(model, count=0, **fields):
    form = FormData()
    for key, value in dict(
        kind="image", image_model=model, prompt="Add a red scarf", **fields
    ).items():
        form.add_field(key, str(value))
    for i in range(count):
        out = io.BytesIO()
        Image.new("RGB", (48, 64)).save(out, format="PNG")
        form.add_field(
            "ref_image",
            out.getvalue(),
            filename=f"ref-{i}.png",
            content_type="image/png",
        )
    return form


class PictureModelTests(APIAppTestCase):
    async def test_fast_models_generate_and_edit(self):
        for model, steps in [("flux-klein-4b", 4), ("qwen-image-21-turbo", 8)]:
            for count in (0, 2):
                response = await self.client.post(
                    "/api/jobs", data=picture_form(model, count)
                )
                self.assertEqual(response.status, 201, await response.text())
                job = await response.json()
                self.assertEqual(job["mode"], "i2i" if count else "t2i")
                self.assertEqual(job["image_model"], model)
                self.assertEqual(job["models"]["steps"], steps)
                self.assertEqual(len(job["refs"]), count)
                for name in job["refs"]:
                    self.assertTrue((self.settings.uploads / name).is_file())
                if count:
                    self.assertAlmostEqual(
                        job["width"] / job["height"], 0.75, delta=0.025
                    )
        self.assertEqual(self.store.count(), 4)

    async def test_invalid_edit_rejected_before_upload_saved(self):
        for form in [
            picture_form("moss", 1),
            picture_form("missing"),
            picture_form("flux-klein-4b", 5),
            picture_form("qwen-image-21-turbo", 1, aspect_ratio="16:9"),
            picture_form("flux-klein-4b", aspect_ratio="image"),
        ]:
            response = await self.client.post("/api/jobs", data=form)
            self.assertEqual(response.status, 400, await response.text())
        self.assertEqual(self.store.count(), 0)
        self.assertEqual(list(self.settings.uploads.iterdir()), [])
        self.assertTrue(self.worker.queue.empty())

    async def test_model_history_filters_old_moss_and_edits(self):
        self.store.create(mode="t2i", prompt="legacy", refs=[])
        self.store.create(mode="t2i", image_model="moss", prompt="moss", refs=[])
        self.store.create(
            mode="i2i", image_model="flux-klein-4b", prompt="edit", refs=[]
        )
        self.store.create(
            mode="t2i", image_model="qwen-image-21-turbo", prompt="qwen", refs=[]
        )
        for model, count in [
            ("moss", 2),
            ("flux-klein-4b", 1),
            ("qwen-image-21-turbo", 1),
        ]:
            response = await self.client.get(
                "/api/jobs", params={"kind": "image", "image_model": model, "limit": 1}
            )
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["X-Total-Count"], str(count))
            self.assertTrue(
                all(j["image_model"] == model for j in await response.json())
            )
        for query in ["kind=image&image_model=missing", "kind=video&image_model=moss"]:
            response = await self.client.get("/api/jobs?" + query)
            self.assertEqual(response.status, 400)
