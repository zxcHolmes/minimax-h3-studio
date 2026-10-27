"""Picture pipeline and helpers."""

import time
from image_models import IMAGE, image_model_info
from engine_errors import Canceled


from .image_runtime import picture_models


def generate_image(engine, *, image_model="moss", ref_paths=(), **kwargs):
    if image_model == "moss":
        return _generate_moss(engine, **kwargs)
    if image_model == "flux-klein-4b":
        from .klein import generate_image as generate
    elif image_model == "qwen-image-21-turbo":
        from .qwen_image import generate_image as generate
    else:
        raise ValueError(f"unknown image model {image_model}")
    return generate(engine, ref_paths=ref_paths, **kwargs)


def _generate_moss(
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
            model, clip, vae = picture_models(engine, "moss")
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
