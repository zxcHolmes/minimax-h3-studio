"""Picture pipeline and helpers."""

import time
from model_catalog import IMAGE, MOSS_CLIP, MOSS_UNET, MOSS_VAE, image_model_info
from engine_errors import Canceled


def _moss_models(engine):
    """(model, clip, vae) for pictures, loaded on first use and kept beside H3."""
    if engine._moss is None:
        model = engine.nodes.UNETLoader().load_unet(MOSS_UNET, "default")[0]
        clip = engine.nodes.CLIPLoader().load_clip(MOSS_CLIP, "moss_image", "default")[
            0
        ]
        vae = engine.nodes.VAELoader().load_vae(MOSS_VAE)[0]
        engine._moss = (model, clip, vae)
    return engine._moss


def generate_image(
    engine, *, prompt, width, height, seed, image_path, thumb_path, on_progress
):
    """Render one picture with MOSS-Image; returns the result record."""
    import torch
    from comfy_extras.nodes_flux import EmptyFlux2LatentImage

    engine._cancel = False
    engine.mm.interrupt_current_processing(False)
    timings = {}
    current = {"stage": None}

    def stage(name):
        current["stage"] = name
        on_progress(name, 0.0)
        timings[name] = time.perf_counter()

    def hook(value, total, preview, node_id=None):
        if current["stage"] == "sampling" and total:
            on_progress("sampling", value / total)

    engine.utils.set_progress_bar_global_hook(hook)
    try:
        with torch.inference_mode():
            if engine._moss is None:
                stage("loading")
            model, clip, vae = _moss_models(engine)
            stage("encoding")
            positive = engine.nodes.CLIPTextEncode().encode(clip, prompt)[0]
            negative = engine.nodes.CLIPTextEncode().encode(clip, IMAGE["negative"])[0]
            latent = EmptyFlux2LatentImage.execute(
                width=width, height=height, batch_size=1
            )[0]
            engine._check()

            stage("sampling")
            samples = engine.nodes.KSampler().sample(
                model,
                seed,
                IMAGE["steps"],
                IMAGE["cfg"],
                IMAGE["sampler"],
                IMAGE["scheduler"],
                positive,
                negative,
                latent,
                denoise=1.0,
            )[0]
            engine._check()

            stage("decoding")
            images = engine.nodes.VAEDecode().decode(vae, samples)[0]

            stage("saving")
            engine._save_picture(images[0], image_path)
            engine._save_thumb(images[0], thumb_path)
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
    return {"steps": IMAGE["steps"], "timings": durations, "models": image_model_info()}
