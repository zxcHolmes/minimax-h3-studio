"""Official Qwen Image 2.1 Turbo generation/edit pipeline, exact 8-step sigma ladder."""

from image_models import QWEN_TURBO_SIGMAS, picture_size
from .image_runtime import ImageRun, picture_models, load_reference


def generate_image(
    engine,
    *,
    prompt,
    width,
    height,
    seed,
    image_path,
    thumb_path,
    on_progress,
    ref_paths=(),
):
    import torch
    from comfy_extras.nodes_qwen import TextEncodeQwenImage21, QwenImage21Cache
    from comfy_extras.nodes_custom_sampler import (
        CFGGuider,
        RandomNoise,
        SamplerCustomAdvanced,
    )

    with (
        torch.inference_mode(),
        ImageRun(engine, "qwen-image-21-turbo", on_progress) as run,
    ):
        run.stage("loading")
        model, clip, vae = picture_models(engine, "qwen-image-21-turbo")
        model = run.node(
            QwenImage21Cache.execute, model=model, device="auto", dtype="default"
        )[0]
        run.stage("encoding")
        refs = {}
        for i, path in enumerate(ref_paths, 1):
            image = load_reference(path, preserve_alpha=True)
            rw, rh = picture_size(
                "qwen-image-21-turbo", image.shape[2] / image.shape[1]
            )
            image = engine.utils.common_upscale(
                image.movedim(-1, 1), rw, rh, "lanczos", "disabled"
            ).movedim(1, -1)
            refs[f"image_{i}"] = image
        positive, negative, latent = run.node(
            TextEncodeQwenImage21.execute,
            clip=clip,
            prompt=prompt,
            negative_prompt="",
            vae=vae if refs else None,
            resolution=0,
            images=refs,
        )
        if not refs:
            latent = {
                "samples": torch.zeros(
                    (1, 64, height // 16, width // 16),
                    device=engine.mm.intermediate_device(),
                )
            }
        # Editing uses the encoder's first-reference canvas, as required by the official graph.
        run.stage("sampling")
        guider = run.node(
            CFGGuider.execute,
            model=model,
            positive=positive,
            negative=negative,
            cfg=1.0,
        )[0]
        noise = run.node(RandomNoise.execute, noise_seed=seed)[0]
        sigmas = torch.tensor(QWEN_TURBO_SIGMAS, dtype=torch.float32)
        samples = run.node(
            SamplerCustomAdvanced.execute,
            noise=noise,
            guider=guider,
            sampler=engine._sampler("euler"),
            sigmas=sigmas,
            latent_image=latent,
        )[0]
        run.stage("decoding")
        images = run.node(engine.nodes.VAEDecode().decode, vae=vae, samples=samples)[0]
        return run.save(images, image_path, thumb_path)
