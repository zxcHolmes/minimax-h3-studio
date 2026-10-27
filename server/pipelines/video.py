"""Video pipeline and helpers."""

import time
from model_catalog import FPS, LORAS, fixed_sampling, frame_count, model_info, unet_file
from engine_errors import Canceled
from run_h3 import load_image


def generate(
    engine,
    *,
    lora,
    prompt,
    width,
    height,
    duration,
    seed,
    lora_strength=1.0,
    sampler=None,
    steps=None,
    image_path=None,
    last_image_path=None,
    ref_paths=(),
    ref_video_paths=(),
    audio_path=None,
    audio_start=0.0,
    video_path,
    thumb_path,
    on_progress,
):
    """Run one job; on_progress(stage, fraction) is called from this thread.

    With `audio_path`, the clip of that file starting at `audio_start` seconds is anchored as the soundtrack
    from frame 0 (MiniMaxH3AddGuide), so the picture is generated to match it: singing, beats, dialogue."""
    import torch

    engine._cancel = False
    engine.mm.interrupt_current_processing(False)
    timings = {}
    family = LORAS[lora]["family"]
    if engine.unet != unet_file(lora):
        on_progress("loading", 0.0)
        timings["loading"] = time.perf_counter()
        engine._use_base(lora)
    model, sigmas, ksampler = engine._lora_model(lora, lora_strength)
    if fixed_sampling(lora):
        sampler = steps = None  # jobs queued before a model choice became fixed
    if sampler:
        ksampler = engine._sampler(sampler)
    if steps and steps != LORAS[lora]["steps"]:
        sigmas = engine.n["BasicScheduler"].execute(model, "simple", steps, 1.0)[0]
    steps = steps or LORAS[lora]["steps"]

    def stage(name):
        on_progress(name, 0.0)
        timings[name] = time.perf_counter()

    def hook(value, total, preview, node_id=None):
        if current["stage"] == "sampling" and total:
            on_progress("sampling", value / total)

    current = {"stage": None}
    engine.utils.set_progress_bar_global_hook(hook)
    try:
        with torch.inference_mode():
            current["stage"] = "encoding"
            stage("encoding")
            # Keyword arguments: ComfyUI has reordered these node signatures between releases.
            if family == "ref2va":
                refs = {
                    f"ref_image_{i}": load_image(p) for i, p in enumerate(ref_paths, 1)
                }
                videos, soundtracks = {}, {}
                for i, p in enumerate(ref_video_paths, 1):
                    videos[f"ref_video_{i}"], track = engine._ref_video(
                        p, width, height, frame_count(duration)
                    )
                    if track:
                        soundtracks[f"ref_video_audio_{i}"] = track
                cond, latent = engine.n["ReferenceToVideo"].execute(
                    clip=engine.clip,
                    vae=engine.vae,
                    audio_vae=engine.audio_vae,
                    prompt=prompt,
                    width=width,
                    height=height,
                    length=frame_count(duration),
                    ref_image_size="match",
                    ref_images=refs,
                    ref_videos=videos,
                    ref_video_audios=soundtracks,
                )
            else:
                first = load_image(image_path) if image_path else None
                last = load_image(last_image_path) if last_image_path else None
                cond, latent = engine.n["ImageToVideo"].execute(
                    clip=engine.clip,
                    vae=engine.vae,
                    prompt=prompt,
                    width=width,
                    height=height,
                    length=frame_count(duration),
                    first_frame=first,
                    last_frame=last,
                )
            if audio_path:
                cond = engine.n["AddGuide"].execute(
                    positive=cond,
                    latent=latent,
                    frame_idx=0,
                    audio_vae=engine.audio_vae,
                    audio=engine._audio_clip(audio_path, audio_start, duration),
                )[0]
            engine._check()

            current["stage"] = "sampling"
            stage("sampling")
            guider = engine.n["BasicGuider"].execute(model, cond)[0]
            noise = engine.n["RandomNoise"].execute(seed)[0]
            samples = engine.n["SamplerCustomAdvanced"].execute(
                noise, guider, ksampler, sigmas, latent
            )[0]
            engine._check()

            current["stage"] = "decoding"
            stage("decoding")
            images = engine.nodes.VAEDecode().decode(engine.vae, samples)[0]
            audio = engine.n["VAEDecodeAudio"].execute(engine.audio_vae, samples)[0]
            engine._check()

            current["stage"] = "saving"
            stage("saving")
            video = engine.n["CreateVideo"].execute(images, float(FPS), audio)[0]
            video.save_to(
                str(video_path),
                format=engine.Types.VideoContainer("mp4"),
                codec=engine.Types.VideoCodec("auto"),
            )
            engine._save_thumb(images[images.shape[0] // 2], thumb_path)
    except engine.mm.InterruptProcessingException:
        raise Canceled()
    finally:
        engine.utils.set_progress_bar_global_hook(None)
        engine.mm.interrupt_current_processing(False)

    end = time.perf_counter()
    names = list(timings)
    durations = {
        n: round((timings[names[i + 1]] if i + 1 < len(names) else end) - timings[n], 1)
        for i, n in enumerate(names)
    }
    return {
        "frames": int(images.shape[0]),
        "steps": steps,
        "timings": durations,
        "models": model_info(lora, lora_strength, sampler, steps),
    }
