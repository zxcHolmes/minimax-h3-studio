"""Flashvsr pipeline and helpers."""

import gc
import sys
import time
from pathlib import Path
from model_catalog import FLASHVSR, FLASHVSR_DIR, FLASHVSR_NODE, upscale_model_info
from engine_errors import Canceled


def _flashvsr_runtime(engine):
    """The FlashVSR+ node's comfy_runtime module, imported once from custom_nodes as a package."""
    import importlib
    import importlib.util

    name = "flashvsr_plus_t8"
    if name not in sys.modules:
        node = Path(engine.comfyui_path) / "custom_nodes" / FLASHVSR_NODE
        spec = importlib.util.spec_from_file_location(
            name,
            node / "flashvsr_plus" / "__init__.py",
            submodule_search_locations=[str(node / "flashvsr_plus")],
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return importlib.import_module(f"{name}.comfy_runtime")


def flashvsr_video(
    engine, *, source_path, width, height, seed, video_path, thumb_path, on_progress
):
    """Upscale a finished video to width×height with FlashVSR v1.1, keeping its audio and frame rate."""
    import re
    import av

    runtime = _flashvsr_runtime(engine)
    engine._cancel = False
    engine.mm.interrupt_current_processing(False)
    on_progress("loading", 0.0)
    start = time.perf_counter()
    # FlashVSR allocates with plain torch, outside ComfyUI's memory management, so the H3 / MOSS / music
    # weights DynamicVRAM keeps resident after a job would leave it out of memory. Move them off the GPU
    # first; their references stay, and the next job streams them back from mmap.
    engine.mm.unload_all_models()
    gc.collect()
    engine.mm.soft_empty_cache()
    if engine._flashvsr is None:
        engine._flashvsr = runtime.ModelHandle(
            **FLASHVSR,
            directory=Path(engine.comfyui_path) / "models" / FLASHVSR_DIR,
            auto_download=False,
            keep_loaded=True,
            device=str(engine.mm.get_torch_device()),
        )
    with av.open(str(source_path)) as container:
        stream = container.streams.video[0]
        source_w, source_h, fps = (
            stream.codec_context.width,
            stream.codec_context.height,
            float(stream.average_rate),
        )
    width, height, canvas_w, canvas_h = runtime.geometry(
        source_w, source_h, 1.0, width, height
    )

    def progress(message):
        match = re.match(r"DiT chunk (\d+)/(\d+)", message)
        if match:
            on_progress("upscaling", int(match[1]) / int(match[2]))

    request = runtime.InferenceRequest(
        input_path=str(source_path),
        output_path=str(video_path),
        height=canvas_h,
        width=canvas_w,
        content_height=height,
        content_width=width,
        fps=fps,
    )
    try:
        result = engine._flashvsr.infer(
            request,
            seed=int(seed),
            options=runtime.Options(),
            progress=progress,
            interrupt=engine.mm.throw_exception_if_processing_interrupted,
        )
    except engine.mm.InterruptProcessingException:
        raise Canceled()
    finally:
        engine.mm.interrupt_current_processing(False)
    on_progress("saving", 0.0)
    frames = engine._thumb_from_video(video_path, thumb_path)
    return {
        "frames": frames,
        "steps": 1,
        "timings": {"upscaling": round(time.perf_counter() - start, 1)},
        "backend": result.metadata.get("actual_backend"),
        "models": upscale_model_info("flashvsr"),
    }
