"""Worker-owned VRAM admission, residency and recovery; no periodic cache eviction."""

import gc
import logging

from engine_errors import MemoryPressure

log = logging.getLogger("h3.memory")
MIB = 1024**2
EXTERNAL_TASKS = {"flashvsr", "pixal3d", "audio_cpp", "llm"}


def is_memory_error(exc, mm=None):
    if isinstance(exc, (MemoryPressure, MemoryError)):
        return True
    if mm is not None and hasattr(mm, "is_oom") and mm.is_oom(exc):
        return True
    return type(exc).__name__ in ("OutOfMemoryError", "CUDAOutOfMemoryError") or any(
        text in str(exc).lower()
        for text in ("cuda out of memory", "cuda error: out of memory")
    )


class MemoryPolicy:
    def __init__(self, engine):
        self.engine = engine
        self.task = None
        self.status = {}

    def reset(self):
        self.task = None
        self.status = {}

    def observe(self):
        mm = self.engine.mm
        device = mm.get_torch_device()
        self.status = {
            **self.status,
            "task": list(self.task) if self.task else None,
            "free_mb": int(mm.get_free_memory(device) // MIB),
            "total_mb": int(mm.get_total_memory(device) // MIB),
        }
        return dict(self.status)

    def prepare(self, task):
        """Keep warm models when possible; native nodes still size their own allocations."""
        mm = self.engine.mm
        device = mm.get_torch_device()
        if device.type != "cuda":
            self.task = task
            return
        llm = getattr(self.engine, "llm", None)
        if llm is not None and llm.running:
            if task[0] == "llm":
                # A warm Strata already owns the VRAM it sized itself for; low free memory is expected.
                self.task = task
                self.status = {"action": "retained", "switch": False}
                self.observe()
                return
            llm.stop()  # Strata keeps nearly all VRAM while it runs; any other job needs it gone.
        audio = getattr(self.engine, "audio_cpp", None)
        if audio is not None and audio.resident_model is not None and task[0] != "audio_cpp":
            # Between audio models audio.cpp keeps two resident and evicts the least recently used itself;
            # unloading on every preset/clone switch reloaded weights for each clip.
            audio.unload()
        reserve = int(mm.minimum_inference_memory())
        if audio is not None and audio.running and (task[0] == "llm" or mm.get_free_memory(device) < reserve):
            audio.stop()  # Release private CUDA caches/context if model unload was insufficient.
        changed = self.task != task
        action = "retained"
        if changed and task[0] in EXTERNAL_TASKS:
            # Mesh and FlashVSR kernels allocate outside DynamicVRAM. Leave the
            # CPU objects cached, but give these runtimes the GPU on entry.
            mm.unload_all_models()
            gc.collect()
            mm.soft_empty_cache()
            action = "offloaded_for_external"
        if mm.get_free_memory(device) < reserve:
            # ComfyUI evicts only as much model memory as it needs here.
            mm.free_memory(reserve, device)
            gc.collect()
            mm.soft_empty_cache()
            action = "reclaimed"
        if mm.get_free_memory(device) < reserve:
            mm.unload_all_models()
            gc.collect()
            mm.soft_empty_cache()
            action = "offloaded"
        free = mm.get_free_memory(device)
        self.status = {
            "action": action,
            "switch": changed,
            "reserve_mb": reserve // MIB,
        }
        if free < reserve:
            self.status["action"] = "blocked"
            self.observe()
            raise MemoryPressure(
                f"Insufficient GPU memory: {free // MIB} MiB available; "
                f"at least {reserve // MIB} MiB execution headroom required. "
                "Task stopped before loading models. Other GPU programs may be using memory."
            )
        self.task = task
        self.observe()
        log.info(
            "task=%s switch=%s action=%s free=%s MiB",
            task,
            changed,
            action,
            free // MIB,
        )

    def recover(self):
        """Run after the exception's inference frames have been released. Never retry blindly."""
        self.engine._after_node()
        self.engine.unload()
        self.status = {"action": "recovered_after_oom"}
        return self.observe()
