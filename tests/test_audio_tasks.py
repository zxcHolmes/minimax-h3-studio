"""Native audio API contracts, exported timings, model residency and fault boundaries."""

import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

from aiohttp import FormData
from api_support import APIAppTestCase
from audio_catalog import ASR_MODELS, native_id, server_config
from audio_runtime import AudioCppServer
from job_worker import Worker
from runtime_memory import MemoryPolicy
from transcript_exports import export_transcript


def wav_bytes():
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x10\x00" * 16000)
    return out.getvalue()


def form(kind="speech", upload=None, **fields):
    data = FormData()
    for key, value in {"kind": kind, **fields}.items():
        data.add_field(key, str(value))
    if upload:
        data.add_field(
            upload, wav_bytes(), filename="recording.wav", content_type="audio/wav"
        )
    return data


class AudioAPITests(APIAppTestCase):
    async def test_speech_modes_and_video_input_transcription_roundtrip(self):
        for fields in [
            dict(prompt="你好，春天", audio_model="qwen3_tts"),
            dict(
                prompt="Hello",
                audio_model="qwen3_tts",
                speech_mode="design",
                instruction="Warm adult voice",
            ),
            dict(prompt="你好", audio_model="voxcpm2", speech_mode="clone"),
        ]:
            r = await self.client.post(
                "/api/jobs",
                data=form(
                    upload="voice_audio"
                    if fields.get("speech_mode") == "clone"
                    else None,
                    **fields,
                ),
            )
            self.assertEqual(r.status, 201, await r.text())
            j = await r.json()
            self.assertEqual(j["mode"], "tts")
            self.assertEqual(j["models"]["backend"], "cuda")
        r = await self.client.post(
            "/api/jobs",
            data=form(
                "asr", upload="media", audio_model="qwen3_asr", timestamps="word"
            ),
        )
        self.assertEqual(r.status, 201, await r.text())
        j = await r.json()
        self.assertEqual(j["duration"], 1)
        self.assertEqual(j["audio_options"]["timestamps"], "word")
        self.assertTrue(j["input_media_url"].startswith("/files/uploads/"))

    async def test_invalid_modes_and_timing_do_not_leave_uploads(self):
        cases = [
            form(prompt="Hello", speech_mode="clone"),
            form(prompt="Hello", speech_mode="design"),
            form(prompt="Hi", audio_model="unknown"),
            form(
                "asr",
                upload="media",
                audio_model="vibevoice_asr_streaming",
                timestamps="word",
            ),
            form("asr", upload="media", audio_model="vibevoice_asr", timestamps="word"),
            form("asr"),
        ]
        for data in cases:
            r = await self.client.post("/api/jobs", data=data)
            self.assertEqual(r.status, 400, await r.text())
        self.assertEqual(self.store.count(), 0)
        self.assertEqual(list(self.settings.uploads.iterdir()), [])

    async def test_omnivoice_design_uses_native_attributes(self):
        invalid = await self.client.post(
            "/api/jobs",
            data=form(
                prompt="Hello",
                audio_model="omnivoice",
                speech_mode="design",
                instruction="a warm cheerful voice",
            ),
        )
        self.assertEqual(invalid.status, 400)
        valid = await self.client.post(
            "/api/jobs",
            data=form(
                prompt="Hello",
                audio_model="omnivoice",
                speech_mode="design",
                instruction="女，青年，中音调",
            ),
        )
        self.assertEqual(valid.status, 201, await valid.text())
        self.assertEqual(
            (await valid.json())["audio_options"]["instruction"],
            "female, young adult, moderate pitch",
        )

    async def test_webm_recording_without_duration_metadata(self):
        import av
        import numpy as np

        out = io.BytesIO()
        with av.open(out, mode="w", format="webm", options={"live": "1"}) as container:
            stream = container.add_stream("libopus", rate=16000)
            stream.layout = "mono"
            frame = av.AudioFrame.from_ndarray(
                np.zeros((1, 16000), dtype=np.float32), format="flt", layout="mono"
            )
            frame.sample_rate = 16000
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
        data = form("asr", audio_model="qwen3_asr")
        data.add_field(
            "media",
            out.getvalue(),
            filename="recording.webm",
            content_type="audio/webm",
        )
        response = await self.client.post("/api/jobs", data=data)
        self.assertEqual(response.status, 201, await response.text())
        self.assertAlmostEqual((await response.json())["duration"], 1, delta=0.1)

    async def test_retired_model_history_stays_readable_without_reenabling_it(self):
        job = self.store.create(
            mode="asr",
            audio_model="vibevoice_asr",
            prompt="Archived transcript",
            refs=[],
        )
        response = await self.client.get("/api/jobs/" + job["id"])
        self.assertEqual(response.status, 200)
        self.assertTrue((await response.json())["models"]["retired"])
        response = await self.client.post(
            "/api/jobs", data=form("asr", upload="media", audio_model="vibevoice_asr")
        )
        self.assertEqual(response.status, 400)

    async def test_history_worker_results_and_deletion(self):
        engine = SimpleNamespace(
            generate_speech=Mock(return_value={"seconds": 2, "sample_rate": 24000}),
            transcribe=Mock(
                return_value={
                    "seconds": 1,
                    "transcript": {"text": "hello", "exports": {"txt": "test.txt"}},
                }
            ),
        )
        worker = Worker(self.store, engine, self.settings)
        r = await self.client.post(
            "/api/jobs", data=form(prompt="hello", audio_model="qwen3_tts")
        )
        speech = await r.json()
        worker._run_one(speech["id"])
        view = await (await self.client.get("/api/jobs/" + speech["id"])).json()
        self.assertTrue(view["audio_url"].startswith("/files/speech/"))
        self.assertEqual(
            engine.generate_speech.call_args.kwargs["audio_path"].parent,
            self.settings.speech,
        )
        r = await self.client.post(
            "/api/jobs", data=form("asr", upload="media", audio_model="qwen3_asr")
        )
        asr = await r.json()
        worker._run_one(asr["id"])
        (self.settings.transcripts / "test.txt").write_text("hello")
        response = await self.client.get("/api/jobs?kind=asr&audio_model=qwen3_asr")
        result = await response.json()
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["transcript_urls"]["txt"], "/files/transcripts/test.txt"
        )
        response = await self.client.get("/api/jobs?kind=speech&audio_model=voxcpm2")
        self.assertEqual(await response.json(), [])
        response = await self.client.delete("/api/jobs/" + asr["id"])
        self.assertEqual(response.status, 200)
        self.assertFalse((self.settings.transcripts / "test.txt").exists())
        self.assertFalse((self.settings.uploads / asr["input_media"]).exists())


class MediaTimelineTests(unittest.TestCase):
    def test_delayed_video_audio_keeps_its_original_timeline(self):
        import av
        import numpy as np
        from fractions import Fraction
        from audio_media import to_wav

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "delayed.mkv"
            with av.open(str(source), "w") as output:
                video = output.add_stream("mpeg4", rate=1)
                video.width = video.height = 16
                video.pix_fmt = "yuv420p"
                audio = output.add_stream("pcm_s16le", rate=16000)
                audio.layout = "mono"
                vf = av.VideoFrame.from_ndarray(
                    np.zeros((16, 16, 3), dtype=np.uint8), format="rgb24"
                )
                vf.pts = 0
                vf.time_base = Fraction(1, 1)
                for p in video.encode(vf):
                    output.mux(p)
                for p in video.encode(None):
                    output.mux(p)
                af = av.AudioFrame.from_ndarray(
                    np.full((1, 16000), 1000, dtype=np.int16),
                    format="s16",
                    layout="mono",
                )
                af.sample_rate = 16000
                af.pts = 16000
                af.time_base = Fraction(1, 16000)
                for p in audio.encode(af):
                    output.mux(p)
                for p in audio.encode(None):
                    output.mux(p)
            self.assertAlmostEqual(
                to_wav(
                    source,
                    root / "aligned.wav",
                    sample_rate=16000,
                    check=lambda: None,
                    preserve_timeline=True,
                ),
                2,
            )
            with wave.open(str(root / "aligned.wav")) as result:
                self.assertEqual(result.readframes(16000), bytes(32000))
                self.assertNotEqual(result.readframes(16000), bytes(32000))
            self.assertAlmostEqual(
                to_wav(
                    source,
                    root / "reference.wav",
                    sample_rate=16000,
                    check=lambda: None,
                ),
                1,
            )


class TranscriptTests(unittest.TestCase):
    def test_word_offsets_make_real_subtitles_and_streaming_has_no_fake_timing(self):
        raw = {
            "text": "Hello world.",
            "sample_rate": 16000,
            "words": [
                {"word": "Hello", "start_sample": 1600, "end_sample": 8000},
                {"word": "world.", "start_sample": 8000, "end_sample": 16000},
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            result = export_transcript(
                raw,
                folder=folder,
                job_id="q",
                duration=1.2,
                timing_source="forced_alignment",
            )
            self.assertEqual(result["words"][0]["start"], 0.1)
            self.assertEqual(
                set(result["exports"]), {"txt", "json", "words", "srt", "vtt"}
            )
            self.assertIn(
                "00:00:00,100 --> 00:00:01,000", (folder / "q.srt").read_text()
            )
            result = export_transcript(
                raw, folder=folder, job_id="s", duration=1.2, timing_source="none"
            )
            self.assertEqual(set(result["exports"]), {"txt", "json"})
            self.assertFalse(result["words"])

    def test_native_speaker_segments_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            result = export_transcript(
                {
                    "text": "你好",
                    "sample_rate": 16000,
                    "speaker_turns": [
                        {
                            "speaker_id": 1,
                            "start_sample": 0,
                            "end_sample": 16000,
                            "text": "你好",
                        }
                    ],
                },
                folder=Path(temp),
                job_id="v",
                duration=1,
                timing_source="native_segments",
            )
            self.assertEqual(result["segments"][0]["speaker"], "1")
            self.assertIn("Speaker 1: 你好", (Path(temp) / "v.srt").read_text())


class RuntimeTests(unittest.TestCase):
    def test_native_variants_are_distinct_and_two_model_residency_is_configured(self):
        config = server_config(Path("/audio"), 8191, 8)
        self.assertEqual(set(ASR_MODELS), {"qwen3_asr"})
        self.assertEqual(
            {m["family"] for m in config["models"] if m["task"] == "asr"}, {"qwen3_asr"}
        )
        self.assertEqual(config["backend"], "cuda")
        self.assertEqual(config["max_loaded_models"], 2)
        self.assertEqual(config["idle_unload_ms"], 0)
        self.assertNotEqual(
            native_id("qwen3_tts", "clone"), native_id("qwen3_tts", "design")
        )
        entry = next(m for m in config["models"] if m["id"] == "qwen3_asr")
        self.assertIn("qwen3_asr.forced_aligner_path", entry["session_options"])

    def test_resident_server_is_reused_and_unload_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = AudioCppServer(temp, Path(temp) / "state")
            runtime.process = Mock()
            runtime.process.poll.return_value = None
            runtime.configured_ids = {"voxcpm2"}
            runtime.resident_model = "voxcpm2"
            runtime.start("voxcpm2", lambda: None)
            runtime.process.terminate.assert_not_called()
            with patch.object(
                runtime, "_request", return_value={"unloaded": ["voxcpm2"]}
            ) as req:
                runtime.unload()
                req.assert_called_once()
            self.assertIsNone(runtime.resident_model)
            self.assertTrue(runtime.running)
            runtime.stop()

    def test_occupied_port_is_not_adopted_or_killed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "runtime").mkdir()
            (root / "runtime" / "server").touch()
            (root / "runtime" / ".studio-runtime.json").write_text(
                json.dumps({"binary": "server"})
            )
            runtime = AudioCppServer(root, root / "state")
            with patch("audio_runtime.socket.socket") as socket:
                socket.return_value.__enter__.return_value.connect_ex.return_value = 0
                with self.assertRaisesRegex(RuntimeError, "occupied"):
                    runtime.start("qwen3_asr", lambda: None)
            self.assertIsNone(runtime.process)

    def test_cross_engine_handoff_releases_audio_weights_but_same_audio_stays_warm(
        self,
    ):
        mm = SimpleNamespace(
            get_torch_device=Mock(return_value=SimpleNamespace(type="cuda")),
            get_free_memory=Mock(return_value=8 * 1024**3),
            get_total_memory=Mock(return_value=24 * 1024**3),
            minimum_inference_memory=Mock(return_value=1024**3),
            unload_all_models=Mock(),
            soft_empty_cache=Mock(),
        )
        audio = SimpleNamespace(
            resident_model="voxcpm2", running=True, unload=Mock(), stop=Mock()
        )
        engine = SimpleNamespace(mm=mm, audio_cpp=audio)
        policy = MemoryPolicy(engine)
        policy.task = ("audio_cpp", "voxcpm2")
        policy.prepare(("audio_cpp", "voxcpm2"))
        audio.unload.assert_not_called()
        mm.unload_all_models.assert_not_called()
        policy.prepare(("image", "moss"))
        audio.unload.assert_called_once()
        audio.stop.assert_not_called()
