"""Shared model cache, progress and cleanup for image pipelines."""

import gc
import time
from image_models import IMAGE_MODELS, image_model_info
from engine_errors import Canceled


def load_reference(path, *, preserve_alpha=False):
    """Read EXIF orientation; retain Qwen alpha or composite RGB references over white."""
    import numpy as np
    import torch
    from PIL import Image, ImageOps

    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        if "A" in image.getbands() or "transparency" in image.info:
            image = image.convert("RGBA")
            if not preserve_alpha:
                background = Image.new("RGBA", image.size, "white")
                image = Image.alpha_composite(background, image).convert("RGB")
        else:
            image = image.convert("RGB")
        return torch.from_numpy(np.array(image, dtype=np.float32) / 255.0)[None]


def picture_models(engine, choice):
    if engine._picture_model == choice and engine._picture_models is not None:
        return engine._picture_models
    if engine._picture_models is not None:
        # Release only the old image family's weights, leaving unrelated warm
        # video/music models under DynamicVRAM's normal pressure-based control.
        for component in engine._picture_models:
            engine.mm.unload_model_and_clones(getattr(component, "patcher", component))
        engine._picture_models = engine._moss = None
        engine._picture_model = None
        del component
        gc.collect()
        engine.mm.soft_empty_cache()
    p = IMAGE_MODELS[choice]
    model = engine.nodes.UNETLoader().load_unet(
        unet_name=p["unet"], weight_dtype="default"
    )[0]
    clip = engine.nodes.CLIPLoader().load_clip(
        clip_name=p["clip"], type=p["clip_type"], device="default"
    )[0]
    vae = engine.nodes.VAELoader().load_vae(vae_name=p["vae"])[0]
    engine._picture_models = model, clip, vae
    engine._picture_model = choice
    if choice == "moss":
        engine._moss = engine._picture_models
    return engine._picture_models


class ImageRun:
    def __init__(self, engine, choice, on_progress):
        self.engine, self.choice, self.on_progress = engine, choice, on_progress
        self.timings = {}
        self.current = "loading"

    def __enter__(self):
        self.engine._cancel = False
        self.engine.mm.interrupt_current_processing(False)
        self.engine.utils.set_progress_bar_global_hook(self.hook)
        return self

    def stage(self, name):
        self.engine._check()
        self.current = name
        self.timings[name] = time.perf_counter()
        self.on_progress(name, 0.0)

    def hook(self, value, total, preview, node_id=None):
        self.engine._check()
        if total:
            self.on_progress(self.current, value / total)

    def node(self, fn, *args, **kwargs):
        self.engine._check()
        result = fn(*args, **kwargs)
        self.engine._after_node()
        self.engine._check()
        return result

    def save(self, images, image_path, thumb_path):
        self.stage("saving")
        self.engine._save_picture(images[0], image_path)
        self.engine._save_thumb(images[0], thumb_path)
        end = time.perf_counter()
        names = list(self.timings)
        return {
            "steps": IMAGE_MODELS[self.choice]["steps"],
            "models": image_model_info(self.choice),
            "timings": {
                name: round(
                    (self.timings[names[i + 1]] if i + 1 < len(names) else end)
                    - self.timings[name],
                    1,
                )
                for i, name in enumerate(names)
            },
        }

    def __exit__(self, exc_type, exc, tb):
        self.engine.utils.set_progress_bar_global_hook(None)
        self.engine.mm.interrupt_current_processing(False)
        self.engine._after_node()
        if exc_type and issubclass(
            exc_type, self.engine.mm.InterruptProcessingException
        ):
            raise Canceled() from exc
