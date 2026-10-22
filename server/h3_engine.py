"""Resident MiniMax-H3 Turbo engine on top of ComfyUI's Python API.

The text encoder and VAEs stay loaded for the life of the process. A model choice
(an entry of LORAS) is a base DiT plus optional LoRA, sampler, sigma shift and
attention patches. Bases come in two families, fl2va (text / first frame / first+last
frame) and ref2va (reference images), and in two groups: the MiniMax-H3 checkpoints
that take a LoRA, and FastVideo's distilled FastH3 checkpoints that run without one.
Only one base is resident; a job on another base swaps it out. Each choice is a cheap
ModelPatcher clone of the resident base, built on first use and kept until the base
swaps. All generate() calls must come from a single thread.
"""

import gc
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "comfy_launcher"))

from run_h3 import bootstrap_comfy, load_image, load_larryvrh_nodes  # noqa: E402

FPS = 24

RESOLUTIONS = {"544p": 960 * 544, "768p": 1344 * 768}

# Model groups shown to users: H3 bases take a LoRA, FastH3 bases are distilled and take none.
GROUPS = {
    "h3": "MiniMax-H3 + LoRA",
    "fasth3": "FastVideo FastH3",
}

# Model choices. H3 entries are a LoRA on the family's base in UNETS; FastH3 entries
# name their own `unet` and have no LoRA (`file` None). `resolutions` lists where each
# one was trained or tested; `source` / `unet_source` are the Hugging Face repos
# scripts/prepare_models.py downloads from. The shift has to match the checkpoint:
# ref2v at 6 smears moving subjects into colour blobs. `vsa` turns on comfy_kitchen
# attention plus Video Sparse Attention as in the FastH3 ComfyUI templates.
LORAS = {
    "lightx2v-8step-v1.0": {
        "group": "h3", "family": "fl2va", "source": "lightx2v/Minimax-h3-Turbo", "label": "lightx2v 8-step v1.0", "loader": "core",
        "file": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
        "steps": 8, "shift_video": 12.0, "shift_audio": 3.0, "resolutions": ["544p"],
    },
    "lightx2v-4step-v1.3": {
        "group": "h3", "family": "fl2va", "source": "lightx2v/Minimax-h3-Turbo", "label": "lightx2v 4-step v1.3", "loader": "core",
        "file": "minimax_h3_fl2v_turbo_4step_v1.3_768p_comfyui_bf16.safetensors",
        "steps": 4, "shift_video": 6.0, "shift_audio": 3.0, "resolutions": ["768p"],
    },
    # Needs its own LoRA node (adaLN on the pruned base) and its own 4-step sampler.
    "larryvrh-v4": {
        "group": "h3", "family": "fl2va", "source": "larryvrh/MiniMax-H3-Turbo-Lora", "label": "larryvrh v4 4-step", "loader": "larryvrh",
        "file": "minimax_h3_turbo_v4_step600_ema.safetensors",
        "steps": 4, "shift_video": 12.0, "shift_audio": 3.0, "resolutions": ["544p", "768p"],
    },
    "lightx2v-ref-v0.1": {
        "group": "h3", "family": "ref2va", "source": "lightx2v/Minimax-h3-Turbo", "label": "lightx2v ref2v 4-step v0.1", "loader": "core",
        "file": "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
        "steps": 4, "shift_video": 12.0, "shift_audio": 3.0, "resolutions": ["544p", "768p"],
    },
    "lightx2v-ref-v1.0": {
        "group": "h3", "family": "ref2va", "source": "lightx2v/Minimax-h3-Turbo", "label": "lightx2v ref2v 4-step v1.0", "loader": "core",
        "file": "minimax_h3_ref2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",
        "steps": 4, "shift_video": 12.0, "shift_audio": 3.0, "resolutions": ["768p"],
    },
    # FastVideo's 8-step distilled bases, settings from ComfyUI's FastH3 templates.
    "fasth3-v2": {
        "group": "fasth3", "family": "fl2va", "label": "FastH3 V2 8-step", "loader": "none", "file": None,
        "unet": "fastvideo_fasth3_8step_v2_pruned_int8_convrot.safetensors",
        "unet_source": "FastVideo/FastVideo-FastH3-Comfy", "sampler": "res_multistep",
        "steps": 8, "shift_video": 10.0, "shift_audio": 3.0, "vsa": {"keep": 10, "start": 0.2},
        "resolutions": ["544p", "768p"],
    },
    "fasth3-omniref": {
        "group": "fasth3", "family": "ref2va", "label": "FastH3 OmniRef 8-step", "loader": "none", "file": None,
        "unet": "fasth3_omniref_8step_pruned_int8_convrot.safetensors",
        "unet_source": "FastVideo/FastH3-Omni-Comfy", "sampler": "euler",
        "steps": 8, "shift_video": 12.0, "shift_audio": 3.0, "vsa": {"keep": 10, "start": 0.0},
        "resolutions": ["544p", "768p"],
    },
}

# Recommended LoRA per (family, resolution), used when a request names none.
DEFAULT_LORAS = {
    "fl2va": {"544p": "lightx2v-8step-v1.0", "768p": "lightx2v-4step-v1.3"},
    "ref2va": {"544p": "lightx2v-ref-v0.1", "768p": "lightx2v-ref-v1.0"},
}

# Jobs created before LoRA selection stored a combined preset id instead.
LEGACY_PRESETS = {
    "544p": ("544p", "lightx2v-8step-v1.0"),
    "768p": ("768p", "lightx2v-4step-v1.3"),
    "ref-544p": ("544p", "lightx2v-ref-v0.1"),
    "ref-768p": ("768p", "lightx2v-ref-v1.0"),
}

ASPECT_RATIOS = {"16:9": 16 / 9, "9:16": 9 / 16, "4:3": 4 / 3, "3:4": 3 / 4, "1:1": 1.0}

# Base checkpoints, all from the Comfy-Org/MiniMax-H3 repo (see scripts/prepare_models.py).
UNETS = {
    "fl2va": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "ref2va": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
}
MAX_REFS = 6
CLIP = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"

# Keyframe tags the I2VA prompts in the repo and the ComfyUI docs open with.
I2V_PREFIX = ("For the target video, at 0.00 seconds into the target video, "
              "<Picture 1> (from [Shot 1]) is fully referenced.")
LAST_FRAME_TAG = "At {:.2f} seconds into the target video, <Picture 2> (from [Shot 1]) is fully referenced."


def frame_count(duration):
    """Frames the model renders for `duration` seconds: the 17k+5 grid at 24 fps."""
    n = max(5, round(duration * FPS))
    while n % 17 != 5:
        n += 1
    return n


def unet_file(lora):
    """The base checkpoint a model choice runs on."""
    p = LORAS[lora]
    return p.get("unet") or UNETS[p["family"]]


def model_info(lora):
    """The checkpoints and sampling settings a model choice runs on, as shown to users."""
    p = LORAS[lora]
    vsa = p.get("vsa")
    return {"unet": unet_file(lora), "lora": p["file"], "steps": p["steps"],
            "sampler": "larryvrh turbo" if p["loader"] == "larryvrh" else p.get("sampler", "euler"),
            "shift_video": p["shift_video"], "shift_audio": p["shift_audio"],
            "attention": f"VSA {vsa['keep']}%" if vsa else None}


class Canceled(Exception):
    pass


def canvas_size(resolution, ratio):
    """Width/height with the resolution's pixel area at `ratio`, each a multiple of 32."""
    area = RESOLUTIONS[resolution]
    width = max(32, round(math.sqrt(area * ratio) / 32) * 32)
    height = max(32, round(math.sqrt(area / ratio) / 32) * 32)
    return width, height


def with_keyframe_prefix(prompt, duration, last_frame=False):
    """Reference the keyframes the way the official I2VA prompts do, unless the prompt already does."""
    tags = []
    if "<Picture 1>" not in prompt:
        tags.append(I2V_PREFIX)
    if last_frame and "<Picture 2>" not in prompt:
        tags.append(LAST_FRAME_TAG.format((frame_count(duration) - 1) / FPS))
    if not tags:
        return prompt
    prefix = " ".join(tags)
    label = "integrated_multimodal_description:"
    if prompt.lstrip().startswith(label):
        body = prompt.lstrip()[len(label):].lstrip()
        return f"{label} {prefix}\n\n{body}"
    return f"{prefix}\n\n{prompt}"


class H3Engine:
    def __init__(self, comfyui_path, comfy_argv):
        self.comfyui_path = comfyui_path
        self.comfy_argv = comfy_argv
        self._models = {}
        self.family = None
        self.unet = None
        self.base = None
        self._cancel = False

    def bootstrap(self):
        """ComfyUI's process-level setup (CLI args, DynamicVRAM). Call from the main thread."""
        bootstrap_comfy(self.comfyui_path, self.comfy_argv)

    def load(self):
        """Create the model objects. Call from the thread that will run generate()."""
        import nodes
        import comfy.model_management
        import comfy.utils
        from comfy_extras.nodes_audio import VAEDecodeAudio
        from comfy_extras.nodes_custom_sampler import (
            BasicGuider, BasicScheduler, KSamplerSelect, RandomNoise, SamplerCustomAdvanced,
        )
        from comfy_extras.nodes_minimax_h3 import (
            MiniMaxH3ImageToVideo, MiniMaxH3ReferenceToVideo, MiniMaxH3SigmaShift,
        )
        from comfy_extras.nodes_video import CreateVideo
        from comfy_api.latest import Types

        self.nodes = nodes
        self.mm = comfy.model_management
        self.utils = comfy.utils
        self.n = {
            "VAEDecodeAudio": VAEDecodeAudio, "BasicGuider": BasicGuider,
            "BasicScheduler": BasicScheduler, "RandomNoise": RandomNoise,
            "SamplerCustomAdvanced": SamplerCustomAdvanced, "ImageToVideo": MiniMaxH3ImageToVideo,
            "ReferenceToVideo": MiniMaxH3ReferenceToVideo,
            "SigmaShift": MiniMaxH3SigmaShift, "CreateVideo": CreateVideo, "KSamplerSelect": KSamplerSelect,
        }
        self.Types = Types

        self.clip = nodes.CLIPLoader().load_clip(CLIP, "minimax", "default")[0]
        self.vae = nodes.VAELoader().load_vae(VIDEO_VAE)[0]
        self.audio_vae = nodes.VAELoader().load_vae(AUDIO_VAE)[0]
        self._samplers = {}
        self._turbo = None
        self._use_base(DEFAULT_LORAS["fl2va"]["544p"])

    def _sampler(self, name):
        if name not in self._samplers:
            self._samplers[name] = self.n["KSamplerSelect"].execute(name)[0]
        return self._samplers[name]

    def _use_base(self, lora):
        """Make the base DiT of model choice `lora` the resident one, unloading the previous base first."""
        unet = unet_file(lora)
        if self.unet == unet:
            return False
        if self.base is not None:
            # Drop every reference to the old DiT (its clones share its weights)
            # so ComfyUI can release the VRAM and the process can release the RAM.
            self._models.clear()
            self.base = None
            self.unet = None
            self.family = None
            self.mm.unload_all_models()
            gc.collect()
            self.mm.soft_empty_cache()
        self.base = self.nodes.UNETLoader().load_unet(unet, "default")[0]
        self.unet = unet
        self.family = LORAS[lora]["family"]
        for key in DEFAULT_LORAS[self.family].values():
            if unet_file(key) == unet:
                self._lora_model(key)
        return True

    def _lora_model(self, key):
        """(model, sigmas, sampler) for a model choice on the resident DiT."""
        if key not in self._models:
            p = LORAS[key]
            model = self.n["SigmaShift"].execute(self.base, p["shift_video"], p["shift_audio"])[0]
            if p["loader"] == "larryvrh":
                turbo = self._larryvrh_nodes()
                model = turbo.MiniMaxH3TurboLoRA().apply_lora(model, p["file"], 1.0)[0]
                sampler = turbo.MiniMaxH3TurboSampler().get_sampler()[0]
            else:
                if p["file"]:
                    model = self.nodes.LoraLoaderModelOnly().load_lora_model_only(model, p["file"], 1.0)[0]
                sampler = self._sampler(p.get("sampler", "euler"))
            if p.get("vsa"):
                from comfy_extras.nodes_model_advanced import ModelAttentionBackend
                from comfy_extras.nodes_sparse_attention import BlockSparseAttention
                model = ModelAttentionBackend.execute(model=model, attention="comfy kitchen attention")[0]
                model = BlockSparseAttention.execute(
                    model=model, selection={"selection": "vsa", "keep_percent": p["vsa"]["keep"]},
                    start_percent=p["vsa"]["start"], end_percent=1.0, dense_blocks="", min_tokens=12288,
                    extra_tokens=256, sink_conditioning="exact_kv_and_rows")[0]
            sigmas = self.n["BasicScheduler"].execute(model, "simple", p["steps"], 1.0)[0]
            self._models[key] = (model, sigmas, sampler)
        return self._models[key]

    def _larryvrh_nodes(self):
        if self._turbo is None:
            self._turbo = load_larryvrh_nodes(self.comfyui_path)
        return self._turbo

    def cancel(self):
        self._cancel = True
        self.mm.interrupt_current_processing(True)

    def _check(self):
        if self._cancel:
            raise Canceled()

    def generate(self, *, lora, prompt, width, height, duration, seed, image_path=None, last_image_path=None,
                 ref_paths=(), video_path, thumb_path, on_progress):
        """Run one job; on_progress(stage, fraction) is called from this thread."""
        import torch

        self._cancel = False
        self.mm.interrupt_current_processing(False)
        timings = {}
        family = LORAS[lora]["family"]
        if self.unet != unet_file(lora):
            on_progress("loading", 0.0)
            timings["loading"] = time.perf_counter()
            self._use_base(lora)
        model, sigmas, sampler = self._lora_model(lora)
        steps = LORAS[lora]["steps"]

        def stage(name):
            on_progress(name, 0.0)
            timings[name] = time.perf_counter()

        def hook(value, total, preview, node_id=None):
            if current["stage"] == "sampling" and total:
                on_progress("sampling", value / total)

        current = {"stage": None}
        self.utils.set_progress_bar_global_hook(hook)
        try:
            with torch.inference_mode():
                current["stage"] = "encoding"
                stage("encoding")
                # Keyword arguments: ComfyUI has reordered these node signatures between releases.
                if family == "ref2va":
                    refs = {f"ref_image_{i}": load_image(p) for i, p in enumerate(ref_paths, 1)}
                    cond, latent = self.n["ReferenceToVideo"].execute(
                        clip=self.clip, vae=self.vae, audio_vae=self.audio_vae, prompt=prompt,
                        width=width, height=height, length=frame_count(duration),
                        ref_image_size="match", ref_images=refs)
                else:
                    first = load_image(image_path) if image_path else None
                    last = load_image(last_image_path) if last_image_path else None
                    cond, latent = self.n["ImageToVideo"].execute(
                        clip=self.clip, vae=self.vae, prompt=prompt, width=width, height=height,
                        length=frame_count(duration), first_frame=first, last_frame=last)
                self._check()

                current["stage"] = "sampling"
                stage("sampling")
                guider = self.n["BasicGuider"].execute(model, cond)[0]
                noise = self.n["RandomNoise"].execute(seed)[0]
                samples = self.n["SamplerCustomAdvanced"].execute(noise, guider, sampler, sigmas, latent)[0]
                self._check()

                current["stage"] = "decoding"
                stage("decoding")
                images = self.nodes.VAEDecode().decode(self.vae, samples)[0]
                audio = self.n["VAEDecodeAudio"].execute(self.audio_vae, samples)[0]
                self._check()

                current["stage"] = "saving"
                stage("saving")
                video = self.n["CreateVideo"].execute(images, float(FPS), audio)[0]
                video.save_to(str(video_path), format=self.Types.VideoContainer("mp4"),
                              codec=self.Types.VideoCodec("auto"))
                self._save_thumb(images[images.shape[0] // 2], thumb_path)
        except self.mm.InterruptProcessingException:
            raise Canceled()
        finally:
            self.utils.set_progress_bar_global_hook(None)
            self.mm.interrupt_current_processing(False)

        end = time.perf_counter()
        names = list(timings)
        durations = {n: round((timings[names[i + 1]] if i + 1 < len(names) else end) - timings[n], 1)
                     for i, n in enumerate(names)}
        return {"frames": int(images.shape[0]), "steps": steps, "timings": durations,
                "models": model_info(lora)}

    @staticmethod
    def _save_thumb(frame, path):
        import numpy as np
        from PIL import Image

        pixels = (frame.clamp(0, 1).cpu().float().numpy() * 255).round().astype(np.uint8)
        img = Image.fromarray(pixels)
        img.thumbnail((640, 640))
        img.save(path, quality=85)
