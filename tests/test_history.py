"""History regression tests."""

from api_support import APIAppTestCase


class HistoryTests(APIAppTestCase):
    async def test_history_kind_filters_count_and_pagination(self):
        for mode in (
            "t2v",
            "i2v",
            "fl2v",
            "r2v",
            "upscale",
            "t2i",
            "t2i",
            "t2m",
            "i23d",
        ):
            self.store.create(mode=mode, prompt="test", refs=[])
        for kind, modes, count in (
            ("video", {"t2v", "i2v", "fl2v", "r2v", "upscale"}, 5),
            ("image", {"t2i"}, 2),
            ("music", {"t2m"}, 1),
            ("3d", {"i23d"}, 1),
        ):
            response = await self.client.get("/api/jobs", params={"kind": kind})
            jobs = await response.json()
            self.assertEqual(response.status, 200)
            self.assertEqual(int(response.headers["X-Total-Count"]), count)
            self.assertEqual(len(jobs), count)
            self.assertTrue(all(j["mode"] in modes for j in jobs))
        first = await self.client.get("/api/jobs?kind=image&limit=1")
        second = await self.client.get("/api/jobs?kind=image&limit=1&offset=1")
        self.assertEqual(second.headers["X-Total-Count"], "2")
        self.assertNotEqual(
            (await first.json())[0]["id"], (await second.json())[0]["id"]
        )
        all_jobs = await self.client.get("/api/jobs")
        self.assertEqual(all_jobs.headers["X-Total-Count"], "9")
        self.assertEqual(len(await all_jobs.json()), 9)

    async def test_empty_and_invalid_history_filters(self):
        response = await self.client.get("/api/jobs?kind=3d")
        self.assertEqual(await response.json(), [])
        self.assertEqual(response.headers["X-Total-Count"], "0")
        for query in ("kind=unknown", "limit=nan", "offset=bad"):
            response = await self.client.get("/api/jobs?" + query)
            self.assertEqual(response.status, 400)
