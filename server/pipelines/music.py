"""Music pipeline and helpers."""

import time
from model_catalog import MUSIC, MUSIC_CLIP, MUSIC_UNET, MUSIC_VAE, music_model_info
from engine_errors import Canceled


def _music_models(engine):
    """(model, clip, vae) for music, loaded on first use and kept beside H3."""
    if engine._music is None:
        model = engine.nodes.UNETLoader().load_unet(MUSIC_UNET, "default")[0]
        clip = engine.nodes.CLIPLoader().load_clip(MUSIC_CLIP, "minimax", "default")[0]
        vae = engine.nodes.VAELoader().load_vae(MUSIC_VAE)[0]
        engine._music = (model, clip, vae)
    return engine._music


def generate_music(engine, *, caption, lyrics, duration, seed, audio_path, on_progress):
    """Render one song with MiniMax Music 3; returns the result record. The model may end before `duration`."""
    import torch
    from comfy_extras.nodes_audio import VAEDecodeAudioTiled
    from comfy_extras.nodes_minimax_music import (
        EmptyMiniMaxMusic3LatentAudio,
        MiniMaxMusic3TextEncode,
    )

    engine._cancel = False
    engine.mm.interrupt_current_processing(False)
    timings = {}
    current = {"stage": None}

    def stage(name):
        engine._after_node()
        current["stage"] = name
        on_progress(name, 0.0)
        timings[name] = time.perf_counter()

    # The text encoder reports progress against the duration limit, the sampler against its steps.
    def hook(value, total, preview, node_id=None):
        if current["stage"] in ("composing", "sampling") and total:
            on_progress(current["stage"], value / total)

    engine.utils.set_progress_bar_global_hook(hook)
    try:
        with torch.inference_mode():
            if engine._music is None:
                stage("loading")
            model, clip, vae = _music_models(engine)
            stage("composing")
            positive, seconds = MiniMaxMusic3TextEncode.execute(
                clip=clip,
                caption=caption,
                lyrics=lyrics,
                seed=seed,
                max_duration=float(duration),
                cfg_scale=MUSIC["encode_cfg"],
                top_k=MUSIC["encode_top_k"],
            )
            negative = engine.nodes.ConditioningZeroOut().zero_out(positive)[0]
            latent = EmptyMiniMaxMusic3LatentAudio.execute(
                seconds=seconds, batch_size=1
            )[0]
            engine._check()

            stage("sampling")
            samples = engine.nodes.KSampler().sample(
                model,
                seed,
                MUSIC["steps"],
                MUSIC["cfg"],
                MUSIC["sampler"],
                MUSIC["scheduler"],
                positive,
                negative,
                latent,
                denoise=1.0,
            )[0]
            engine._check()

            stage("decoding")
            audio = VAEDecodeAudioTiled.execute(
                vae=vae,
                samples=samples,
                tile_size=MUSIC["tile"],
                overlap=MUSIC["overlap"],
            )[0]

            stage("saving")
            engine._save_mp3(audio, audio_path)
    except engine.mm.InterruptProcessingException:
        raise Canceled()
    finally:
        engine._after_node()
        engine.utils.set_progress_bar_global_hook(None)
        engine.mm.interrupt_current_processing(False)

    end = time.perf_counter()
    names = list(timings)
    durations = {
        n: round((timings[names[i + 1]] if i + 1 < len(names) else end) - timings[n], 1)
        for i, n in enumerate(names)
    }
    return {
        "seconds": round(float(seconds), 2),
        "steps": MUSIC["steps"],
        "timings": durations,
        "models": music_model_info(),
    }
