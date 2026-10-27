"""Seedvr2 pipeline and helpers."""

import time
from model_catalog import SEEDVR2_UNET, SEEDVR2_VAE, UPSCALE, upscale_model_info
from engine_errors import Canceled


def _seedvr2_models(engine):
    """(model, vae) for upscaling, loaded on first use and kept beside H3."""
    if engine._seedvr2 is None:
        model = engine.nodes.UNETLoader().load_unet(SEEDVR2_UNET, "default")[0]
        vae = engine.nodes.VAELoader().load_vae(SEEDVR2_VAE)[0]
        engine._seedvr2 = (model, vae)
    return engine._seedvr2


def upscale_video(
    engine, *, source_path, width, height, seed, video_path, thumb_path, on_progress
):
    """Upscale a finished video to width×height with SeedVR2, keeping its audio and frame rate."""
    import torch
    from comfy_api.latest import InputImpl
    from comfy_extras.nodes_seedvr import (
        SeedVR2Conditioning,
        SeedVR2PostProcessing,
        SeedVR2Preprocess,
        SeedVR2TemporalChunk,
        SeedVR2TemporalMerge,
    )

    engine._cancel = False
    engine.mm.interrupt_current_processing(False)
    timings = {}

    def stage(name):
        on_progress(name, 0.0)
        timings[name] = time.perf_counter()

    try:
        with torch.inference_mode():
            if engine._seedvr2 is None:
                stage("loading")
            model, vae = _seedvr2_models(engine)
            stage("reading")
            source = InputImpl.VideoFromFile(str(source_path)).get_components()
            count = source.images.shape[0]
            resized = engine.utils.common_upscale(
                source.images.movedim(-1, 1), width, height, "lanczos", "disabled"
            ).movedim(1, -1)
            padded = SeedVR2Preprocess.execute(resized_images=resized)[0]
            latent = engine.nodes.VAEEncode().encode(vae, padded)[0]
            chunks, overlap = SeedVR2TemporalChunk.execute(
                latent=latent,
                temporal_overlap=UPSCALE["overlap"],
                chunking_mode={"chunking_mode": "auto"},
            )
            engine._check()

            stage("upscaling")
            sampled = []
            for i, chunk in enumerate(chunks):
                positive, negative = SeedVR2Conditioning.execute(
                    model=model, vae_conditioning=chunk
                )
                sampled.append(
                    engine.nodes.KSampler().sample(
                        model,
                        seed,
                        UPSCALE["steps"],
                        UPSCALE["cfg"],
                        UPSCALE["sampler"],
                        UPSCALE["scheduler"],
                        positive,
                        negative,
                        chunk,
                        denoise=1.0,
                    )[0]
                )
                on_progress("upscaling", (i + 1) / len(chunks))
                engine._check()
            merged = (
                sampled[0]
                if len(sampled) == 1
                else SeedVR2TemporalMerge.execute(
                    latents=sampled, temporal_overlap=[overlap]
                )[0]
            )

            stage("decoding")
            images = engine.nodes.VAEDecode().decode(vae, merged)[0]
            images = SeedVR2PostProcessing.execute(
                images=images,
                original_resized_images=resized,
                color_correction_method=UPSCALE["color"],
            )[0]
            images = images.reshape(-1, *images.shape[-3:])[:count]
            engine._check()

            stage("saving")
            video = engine.n["CreateVideo"].execute(
                images, float(source.frame_rate), source.audio
            )[0]
            video.save_to(
                str(video_path),
                format=engine.Types.VideoContainer("mp4"),
                codec=engine.Types.VideoCodec("auto"),
            )
            engine._save_thumb(images[images.shape[0] // 2], thumb_path)
    except engine.mm.InterruptProcessingException:
        raise Canceled()
    finally:
        engine.mm.interrupt_current_processing(False)

    end = time.perf_counter()
    names = list(timings)
    durations = {
        n: round((timings[names[i + 1]] if i + 1 < len(names) else end) - timings[n], 1)
        for i, n in enumerate(names)
    }
    return {
        "frames": int(images.shape[0]),
        "chunks": len(chunks),
        "steps": UPSCALE["steps"],
        "timings": durations,
        "models": upscale_model_info(),
    }
