"""Native speech and transcription pipelines; never call ComfyUI inference nodes."""

import tempfile
import time
from pathlib import Path

from audio_catalog import ASR_MODELS, LANGUAGES, native_id, model_info
from audio_media import to_wav, wav_info
from transcript_exports import export_transcript


def speech(engine, *, model, text, options, source_path, seed, audio_path, on_progress, check=None, owner=None):
    """check/owner: per-job cancellation when several speech jobs share the instance pool."""
    start = time.perf_counter()
    runtime = engine.audio_cpp
    if runtime is None:
        raise RuntimeError("audio.cpp is not configured")
    check = check or engine._check
    mode = options["speech_mode"]
    native = native_id(model, mode)
    request = {
        "model": native,
        "input": text,
        "response_format": "wav",
        "seed": seed % 2**32,
    }
    controls = {}
    if model == "qwen3_tts":
        controls["language"] = LANGUAGES.get(options.get("language"), "Auto").lower()
        controls["text_chunk_size"] = 512
        if mode == "generate":
            request["voice"] = options.get("voice") or "Vivian"
        elif mode == "clone" and not options.get("reference_text"):
            controls["x_vector_only_mode"] = True
    elif model == "omnivoice" and options.get("language") not in ("", "auto", None):
        controls["language"] = options["language"]
    if options.get("instruction"):
        if model == "voxcpm2":
            request["input"] = (
                "(" + options["instruction"].replace(")", "）") + ")" + text
            )
        else:
            controls["instruct"] = options["instruction"]
    request["options"] = controls
    on_progress("loading", 0.0)
    with tempfile.TemporaryDirectory(prefix="speech-", dir=audio_path.parent) as temp:
        if source_path:
            on_progress("preprocessing", 0.0)
            reference = Path(temp) / "reference.wav"
            to_wav(source_path, reference, sample_rate=24000, check=check)
            request["voice_ref"] = str(reference)
            if options.get("reference_text"):
                request["reference_text"] = options["reference_text"]
        on_progress("synthesizing", 0.0)
        data = runtime.infer(
            native, "/v1/audio/speech", request, check, binary=True, owner=owner
        )
        seconds, rate = wav_info(data)
        check()
        on_progress("saving", 0.0)
        part = Path(temp) / "speech.wav"
        part.write_bytes(data)
        part.replace(audio_path)
    return {
        "seconds": seconds,
        "sample_rate": rate,
        "models": model_info(model, mode),
        "timings": {"speech": round(time.perf_counter() - start, 1)},
    }


def transcribe(engine, *, model, source_path, options, folder, job_id, on_progress):
    start = time.perf_counter()
    runtime = engine.audio_cpp
    if runtime is None:
        raise RuntimeError("audio.cpp is not configured")
    on_progress("preprocessing", 0.0)
    with tempfile.TemporaryDirectory(prefix="asr-", dir=folder) as temp:
        wav = Path(temp) / "input.wav"
        duration = to_wav(
            source_path,
            wav,
            sample_rate=16000,
            check=engine._check,
            preserve_timeline=True,
        )
        request = {"model": model, "audio": str(wav)}
        language = options.get("language", "auto")
        if language != "auto":
            request["language"] = LANGUAGES.get(language, language)
        controls = {}
        if model == "qwen3_asr":
            controls.update(
                return_timestamps=options["timestamps"] != "none",
                preserve_punctuation=True,
            )
            if controls["return_timestamps"]:
                from audio_catalog import AUDIO_WEIGHTS

                aligner = (
                    runtime.root
                    / "models"
                    / AUDIO_WEIGHTS["qwen3_forced_aligner_0_6b_q8_0"]["target"]
                )
                if not aligner.is_file():
                    raise RuntimeError(
                        "Qwen word timestamps require the prepared Forced Aligner GGUF"
                    )
        request["options"] = controls
        on_progress("transcribing", 0.0)
        raw = runtime.infer(
            model, "/v1/audio/transcriptions/details", request, engine._check
        )
        engine._check()
    on_progress("saving", 0.0)
    timing_source = (
        ASR_MODELS[model]["timing_source"]
        if options["timestamps"] != "none"
        else "none"
    )
    transcript = export_transcript(
        raw,
        folder=folder,
        job_id=job_id,
        duration=duration,
        timing_source=timing_source,
    )
    return {
        "seconds": duration,
        "transcript": transcript,
        "models": model_info(model),
        "timings": {"transcribing": round(time.perf_counter() - start, 1)},
    }
