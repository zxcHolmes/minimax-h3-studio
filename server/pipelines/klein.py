"""Official FLUX.2 Klein 4B distilled workflows: generation and reference editing, 4 steps."""

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
    from comfy_extras.nodes_flux import EmptyFlux2LatentImage, Flux2Scheduler
    from comfy_extras.nodes_custom_sampler import (
        CFGGuider,
        RandomNoise,
        SamplerCustomAdvanced,
    )
    from comfy_extras.nodes_edit_model import ReferenceLatent
    from comfy_extras.nodes_post_processing import ImageScaleToTotalPixels

    with torch.inference_mode(), ImageRun(engine, "flux-klein-4b", on_progress) as run:
        run.stage("loading")
        model, clip, vae = picture_models(engine, "flux-klein-4b")
        run.stage("encoding")
        positive = run.node(
            engine.nodes.CLIPTextEncode().encode, clip=clip, text=prompt
        )[0]
        negative = run.node(
            engine.nodes.ConditioningZeroOut().zero_out, conditioning=positive
        )[0]
        for path in ref_paths:
            image = load_reference(path)
            image = run.node(
                ImageScaleToTotalPixels.execute,
                image=image,
                upscale_method="nearest-exact",
                megapixels=1.0,
                resolution_steps=1,
            )[0]
            ref = run.node(engine.nodes.VAEEncode().encode, vae=vae, pixels=image)[0]
            positive = run.node(
                ReferenceLatent.execute, conditioning=positive, latent=ref
            )[0]
            negative = run.node(
                ReferenceLatent.execute, conditioning=negative, latent=ref
            )[0]
        latent = run.node(
            EmptyFlux2LatentImage.execute, width=width, height=height, batch_size=1
        )[0]
        sigmas = run.node(Flux2Scheduler.execute, steps=4, width=width, height=height)[
            0
        ]
        run.stage("sampling")
        guider = run.node(
            CFGGuider.execute,
            model=model,
            positive=positive,
            negative=negative,
            cfg=1.0,
        )[0]
        noise = run.node(RandomNoise.execute, noise_seed=seed)[0]
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
