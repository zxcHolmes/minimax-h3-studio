"""Resident MiniMax-H3 Turbo engine on top of ComfyUI's Python API.

The text encoder and VAEs stay loaded for the life of the process. A model choice
(an entry of LORAS) is a base DiT plus optional LoRA, sampler, sigma shift and
attention patches. Bases come in two families, fl2va (text / first frame / first+last
frame) and ref2va (reference images), and in two groups: the MiniMax-H3 checkpoints
that take a LoRA, and FastVideo's distilled FastH3 checkpoints that run without one.
Only one base is resident; a job on another base swaps it out. Each choice is a cheap
ModelPatcher clone of the resident base, built on first use and kept until the base
swaps. Pictures come from MOSS-Image, loaded on the first picture job and kept resident
beside H3. All generate() / generate_image() calls must come from a single thread.
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
# scripts/prepare_models.py downloads from. The shift has to match the checkpoint.
# `vsa` turns on comfy_kitchen attention plus Video Sparse Attention as in the FastH3
# ComfyUI templates. `fixed` keeps the template's sampler and steps whatever a job asks: FastH3 V2 is
# distilled on a fixed 8-rung ladder and OmniRef fuses 4 of its 32 PDD output heads per Euler step,
# so another sampler or step count leaves what they were trained for. Reference jobs run on FastH3 OmniRef only: the 4-step ref2v LoRAs
# smeared large motion into streaks even at 6-8 steps.
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
    # FastVideo's 8-step distilled bases, settings from ComfyUI's FastH3 templates.
    "fasth3-v2": {
        "group": "fasth3", "family": "fl2va", "label": "FastH3 V2 8-step", "loader": "none", "file": None,
        "unet": "fastvideo_fasth3_8step_v2_pruned_int8_convrot.safetensors",
        "unet_source": "FastVideo/FastVideo-FastH3-Comfy", "sampler": "res_multistep",
        "steps": 8, "shift_video": 10.0, "shift_audio": 3.0, "vsa": {"keep": 10, "start": 0.2}, "fixed": True,
        "resolutions": ["544p", "768p"],
    },
    "fasth3-omniref": {
        "group": "fasth3", "family": "ref2va", "label": "FastH3 OmniRef 8-step", "loader": "none", "file": None,
        "unet": "fasth3_omniref_8step_pruned_int8_convrot.safetensors",
        "unet_source": "FastVideo/FastH3-Omni-Comfy", "sampler": "euler",
        "steps": 8, "shift_video": 12.0, "shift_audio": 3.0, "vsa": {"keep": 10, "start": 0.0}, "fixed": True,
        "resolutions": ["544p", "768p"],
    },
}

# Recommended model choice per (family, resolution), used when a request names none.
DEFAULT_LORAS = {
    "fl2va": {"544p": "lightx2v-8step-v1.0", "768p": "lightx2v-4step-v1.3"},
    "ref2va": {"544p": "fasth3-omniref", "768p": "fasth3-omniref"},
}

# Jobs created before LoRA selection stored a combined preset id instead. The ref ids name
# LoRAs that are gone; those jobs keep the models they ran on in result.models.
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
}
MAX_REFS = 6
CLIP = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_int8_convrot.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"

# Picture generation: MOSS-Image SFT with the settings of ComfyUI's MOSS-Image text-to-image template.
MOSS_REPO = "Comfy-Org/MOSS-Image"
MOSS_UNET = "moss_image_sft_int8_convrot.safetensors"
MOSS_CLIP = "qwen3.5_9b_w4a8_gptq.safetensors"
MOSS_VAE = "flux2-vae_small.safetensors"
IMAGE = {"steps": 25, "cfg": 2.5, "sampler": "er_sde", "scheduler": "simple",
         "negative": "nsfw, worst quality, bad anatomy, watermark, jpeg artifact"}
IMAGE_AREA = 1024 * 1024

# Music generation: MiniMax Music 3 with the settings of ComfyUI's text-to-music template. The text encoder
# writes the acoustic tokens autoregressively from caption + lyrics; the DiT then renders them.
MUSIC_REPO = "Comfy-Org/MiniMax-Music-3"
MUSIC_UNET = "minimax_music3_dit_int8_convrot.safetensors"
MUSIC_CLIP = "minimax_music3_text_encoder_pruned_int8_convrot.safetensors"
MUSIC_VAE = "minimax_music3_dav.safetensors"
MUSIC = {"steps": 30, "cfg": 1.7, "sampler": "euler", "scheduler": "simple",
         "encode_cfg": 1.7, "encode_top_k": 50, "tile": 1536, "overlap": 64}
MUSIC_DURATION_RANGE = (10, 300)

# Upscaling finished videos: SeedVR2 3B with the settings of ComfyUI's SeedVR2 video upscale template
# (one euler step, lanczos pre-resize, no color correction). Two departures: the template samples the whole
# clip at once, here it is split into temporal chunks sized to free VRAM, overlapping by two latent frames
# that are crossfaded; and the template's VAEEncodeTiled / VAEDecodeTiled at 512 px are replaced by the plain
# VAE nodes, whose SeedVR2 path sizes the work from measured memory figures and runs whole frames when they
# fit (tiling itself only when not). The forced 512 px tiles made a 10 s 1080p clip spend 480 of 510 s in the VAE.
SEEDVR2_REPO = "Comfy-Org/SeedVR2"
SEEDVR2_UNET = "seedvr2_3b_int8_convrot.safetensors"
SEEDVR2_VAE = "seedvr2_ema_vae_fp16.safetensors"
UPSCALE = {"steps": 1, "cfg": 1.0, "sampler": "euler", "scheduler": "simple", "color": "none", "overlap": 2}
# Target short side of each upscale choice.
UPSCALE_TARGETS = {"1080p": 1080, "1440p": 1440}

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


# Per-job LoRA strength; 1.0 is what the LoRAs were trained for.
LORA_STRENGTH_RANGE = (0.0, 2.0)

# Samplers a job may pick instead of its model choice's own; ComfyUI's H3 templates use res_multistep.
SAMPLERS = ("euler", "res_multistep", "er_sde")
# Per-job step count instead of the model choice's own; turbo LoRAs also run at more steps than they were distilled for.
STEPS_RANGE = (1, 30)


def unet_file(lora):
    """The base checkpoint a model choice runs on."""
    p = LORAS[lora]
    return p.get("unet") or UNETS[p["family"]]


def fixed_sampling(lora):
    """Whether a model choice ignores a job's sampler and steps: larryvrh's turbo sampler and the FastH3 bases."""
    p = LORAS[lora]
    return p["loader"] == "larryvrh" or p.get("fixed", False)


def sampler_name(lora, sampler=None):
    """The sampler a job runs: its own pick, else the model choice's. larryvrh always uses its turbo sampler."""
    p = LORAS[lora]
    if p["loader"] == "larryvrh":
        return "larryvrh turbo"
    return (not fixed_sampling(lora) and sampler) or p.get("sampler", "euler")


def model_info(lora, strength=1.0, sampler=None, steps=None):
    """The checkpoints and sampling settings a model choice runs on, as shown to users."""
    p = LORAS[lora]
    vsa = p.get("vsa")
    return {"unet": unet_file(lora), "lora": p["file"], "lora_strength": strength if p["file"] else None,
            "steps": (not p.get("fixed") and steps) or p["steps"],
            "sampler": sampler_name(lora, sampler),
            "shift_video": p["shift_video"], "shift_audio": p["shift_audio"],
            "attention": f"VSA {vsa['keep']}%" if vsa else None}


def image_model_info():
    """What picture jobs run on, as shown to users."""
    return {"unet": MOSS_UNET, "lora": None, "lora_strength": None, "steps": IMAGE["steps"],
            "sampler": IMAGE["sampler"], "cfg": IMAGE["cfg"], "text_encoder": MOSS_CLIP}


def music_model_info():
    return {"unet": MUSIC_UNET, "lora": None, "lora_strength": None, "steps": MUSIC["steps"],
            "sampler": MUSIC["sampler"], "cfg": MUSIC["cfg"], "text_encoder": MUSIC_CLIP}


def upscale_model_info():
    return {"unet": SEEDVR2_UNET, "lora": None, "lora_strength": None, "steps": UPSCALE["steps"],
            "sampler": UPSCALE["sampler"], "vae": SEEDVR2_VAE}


def upscale_size(width, height, target):
    """Width/height of a `width`×`height` video scaled so its short side is the target's, both even (H.264)."""
    scale = UPSCALE_TARGETS[target] / min(width, height)
    return max(2, round(width * scale / 2) * 2), max(2, round(height * scale / 2) * 2)


def image_size(ratio):
    """Picture width/height of about one megapixel at `ratio`, each a multiple of 16."""
    width = max(16, round(math.sqrt(IMAGE_AREA * ratio) / 16) * 16)
    height = max(16, round(math.sqrt(IMAGE_AREA / ratio) / 16) * 16)
    return width, height


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
        self._moss = None
        self._music = None
        self._seedvr2 = None
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
            MiniMaxH3AddGuide, MiniMaxH3ImageToVideo, MiniMaxH3ReferenceToVideo, MiniMaxH3SigmaShift,
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
            "ReferenceToVideo": MiniMaxH3ReferenceToVideo, "AddGuide": MiniMaxH3AddGuide,
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

    def _lora_model(self, key, strength=1.0):
        """(model, sigmas, sampler) for a model choice at a LoRA strength on the resident DiT."""
        if (key, strength) not in self._models:
            # Keep the full-strength clones plus only the latest other strength: each holds its LoRA weights.
            for cached in [c for c in self._models if c[1] != 1.0]:
                del self._models[cached]
            p = LORAS[key]
            model = self.n["SigmaShift"].execute(self.base, p["shift_video"], p["shift_audio"])[0]
            if p["loader"] == "larryvrh":
                turbo = self._larryvrh_nodes()
                model = turbo.MiniMaxH3TurboLoRA().apply_lora(model, p["file"], strength)[0]
                sampler = turbo.MiniMaxH3TurboSampler().get_sampler()[0]
            else:
                if p["file"]:
                    model = self.nodes.LoraLoaderModelOnly().load_lora_model_only(model, p["file"], strength)[0]
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
            self._models[(key, strength)] = (model, sigmas, sampler)
        return self._models[(key, strength)]

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

    def _after_node(self):
        """What ComfyUI's executor runs after every node under DynamicVRAM. Autoregressive text encoders
        (MiniMax Music 3) record a per-thread CUDA malloc graph; without this the next job replays a stale one
        and fails with a device-side assert."""
        import comfy.memory_management
        import comfy.model_prefetch
        if comfy.memory_management.aimdo_enabled:
            import comfy_aimdo.model_vbar
            comfy.model_prefetch.cleanup_prefetch_queues()
            self.mm.reset_cast_buffers()
            comfy_aimdo.model_vbar.vbars_reset_watermark_limits()

    def generate(self, *, lora, prompt, width, height, duration, seed, lora_strength=1.0, sampler=None, steps=None,
                 image_path=None,
                 last_image_path=None, ref_paths=(), audio_path=None, audio_start=0.0, video_path, thumb_path,
                 on_progress):
        """Run one job; on_progress(stage, fraction) is called from this thread.

        With `audio_path`, the clip of that file starting at `audio_start` seconds is anchored as the soundtrack
        from frame 0 (MiniMaxH3AddGuide), so the picture is generated to match it: singing, beats, dialogue."""
        import torch

        self._cancel = False
        self.mm.interrupt_current_processing(False)
        timings = {}
        family = LORAS[lora]["family"]
        if self.unet != unet_file(lora):
            on_progress("loading", 0.0)
            timings["loading"] = time.perf_counter()
            self._use_base(lora)
        model, sigmas, ksampler = self._lora_model(lora, lora_strength)
        if fixed_sampling(lora):
            sampler = steps = None  # jobs queued before a model choice became fixed
        if sampler:
            ksampler = self._sampler(sampler)
        if steps and steps != LORAS[lora]["steps"]:
            sigmas = self.n["BasicScheduler"].execute(model, "simple", steps, 1.0)[0]
        steps = steps or LORAS[lora]["steps"]

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
                if audio_path:
                    cond = self.n["AddGuide"].execute(positive=cond, latent=latent, frame_idx=0,
                                                      audio_vae=self.audio_vae,
                                                      audio=self._audio_clip(audio_path, audio_start, duration))[0]
                self._check()

                current["stage"] = "sampling"
                stage("sampling")
                guider = self.n["BasicGuider"].execute(model, cond)[0]
                noise = self.n["RandomNoise"].execute(seed)[0]
                samples = self.n["SamplerCustomAdvanced"].execute(noise, guider, ksampler, sigmas, latent)[0]
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
                "models": model_info(lora, lora_strength, sampler, steps)}

    @staticmethod
    def _audio_clip(path, start, duration):
        """The `duration`-long clip of an audio file from `start` seconds, as a ComfyUI AUDIO dict."""
        from comfy_extras.nodes_audio import load
        waveform, rate = load(str(path))
        begin = int(round(start * rate))
        end = begin + int(math.ceil(frame_count(duration) / FPS * rate))
        clip = waveform[:, begin:end]
        if clip.shape[1] < rate // 10:
            raise ValueError(f"the guide audio has nothing at {start:.2f} s")
        return {"waveform": clip.unsqueeze(0), "sample_rate": rate}

    def _moss_models(self):
        """(model, clip, vae) for pictures, loaded on first use and kept beside H3."""
        if self._moss is None:
            model = self.nodes.UNETLoader().load_unet(MOSS_UNET, "default")[0]
            clip = self.nodes.CLIPLoader().load_clip(MOSS_CLIP, "moss_image", "default")[0]
            vae = self.nodes.VAELoader().load_vae(MOSS_VAE)[0]
            self._moss = (model, clip, vae)
        return self._moss

    def generate_image(self, *, prompt, width, height, seed, image_path, thumb_path, on_progress):
        """Render one picture with MOSS-Image; returns the result record."""
        import torch
        from comfy_extras.nodes_flux import EmptyFlux2LatentImage

        self._cancel = False
        self.mm.interrupt_current_processing(False)
        timings = {}
        current = {"stage": None}

        def stage(name):
            current["stage"] = name
            on_progress(name, 0.0)
            timings[name] = time.perf_counter()

        def hook(value, total, preview, node_id=None):
            if current["stage"] == "sampling" and total:
                on_progress("sampling", value / total)

        self.utils.set_progress_bar_global_hook(hook)
        try:
            with torch.inference_mode():
                if self._moss is None:
                    stage("loading")
                model, clip, vae = self._moss_models()
                stage("encoding")
                positive = self.nodes.CLIPTextEncode().encode(clip, prompt)[0]
                negative = self.nodes.CLIPTextEncode().encode(clip, IMAGE["negative"])[0]
                latent = EmptyFlux2LatentImage.execute(width=width, height=height, batch_size=1)[0]
                self._check()

                stage("sampling")
                samples = self.nodes.KSampler().sample(
                    model, seed, IMAGE["steps"], IMAGE["cfg"], IMAGE["sampler"], IMAGE["scheduler"],
                    positive, negative, latent, denoise=1.0)[0]
                self._check()

                stage("decoding")
                images = self.nodes.VAEDecode().decode(vae, samples)[0]

                stage("saving")
                self._save_picture(images[0], image_path)
                self._save_thumb(images[0], thumb_path)
        except self.mm.InterruptProcessingException:
            raise Canceled()
        finally:
            self.utils.set_progress_bar_global_hook(None)
            self.mm.interrupt_current_processing(False)

        end = time.perf_counter()
        names = list(timings)
        durations = {n: round((timings[names[i + 1]] if i + 1 < len(names) else end) - timings[n], 1)
                     for i, n in enumerate(names)}
        return {"steps": IMAGE["steps"], "timings": durations, "models": image_model_info()}

    def _music_models(self):
        """(model, clip, vae) for music, loaded on first use and kept beside H3."""
        if self._music is None:
            model = self.nodes.UNETLoader().load_unet(MUSIC_UNET, "default")[0]
            clip = self.nodes.CLIPLoader().load_clip(MUSIC_CLIP, "minimax", "default")[0]
            vae = self.nodes.VAELoader().load_vae(MUSIC_VAE)[0]
            self._music = (model, clip, vae)
        return self._music

    def generate_music(self, *, caption, lyrics, duration, seed, audio_path, on_progress):
        """Render one song with MiniMax Music 3; returns the result record. The model may end before `duration`."""
        import torch
        from comfy_extras.nodes_audio import VAEDecodeAudioTiled
        from comfy_extras.nodes_minimax_music import EmptyMiniMaxMusic3LatentAudio, MiniMaxMusic3TextEncode

        self._cancel = False
        self.mm.interrupt_current_processing(False)
        timings = {}
        current = {"stage": None}

        def stage(name):
            self._after_node()
            current["stage"] = name
            on_progress(name, 0.0)
            timings[name] = time.perf_counter()

        # The text encoder reports progress against the duration limit, the sampler against its steps.
        def hook(value, total, preview, node_id=None):
            if current["stage"] in ("composing", "sampling") and total:
                on_progress(current["stage"], value / total)

        self.utils.set_progress_bar_global_hook(hook)
        try:
            with torch.inference_mode():
                if self._music is None:
                    stage("loading")
                model, clip, vae = self._music_models()
                stage("composing")
                positive, seconds = MiniMaxMusic3TextEncode.execute(
                    clip=clip, caption=caption, lyrics=lyrics, seed=seed, max_duration=float(duration),
                    cfg_scale=MUSIC["encode_cfg"], top_k=MUSIC["encode_top_k"])
                negative = self.nodes.ConditioningZeroOut().zero_out(positive)[0]
                latent = EmptyMiniMaxMusic3LatentAudio.execute(seconds=seconds, batch_size=1)[0]
                self._check()

                stage("sampling")
                samples = self.nodes.KSampler().sample(
                    model, seed, MUSIC["steps"], MUSIC["cfg"], MUSIC["sampler"], MUSIC["scheduler"],
                    positive, negative, latent, denoise=1.0)[0]
                self._check()

                stage("decoding")
                audio = VAEDecodeAudioTiled.execute(vae=vae, samples=samples, tile_size=MUSIC["tile"],
                                                    overlap=MUSIC["overlap"])[0]

                stage("saving")
                self._save_mp3(audio, audio_path)
        except self.mm.InterruptProcessingException:
            raise Canceled()
        finally:
            self._after_node()
            self.utils.set_progress_bar_global_hook(None)
            self.mm.interrupt_current_processing(False)

        end = time.perf_counter()
        names = list(timings)
        durations = {n: round((timings[names[i + 1]] if i + 1 < len(names) else end) - timings[n], 1)
                     for i, n in enumerate(names)}
        return {"seconds": round(float(seconds), 2), "steps": MUSIC["steps"], "timings": durations,
                "models": music_model_info()}

    def _seedvr2_models(self):
        """(model, vae) for upscaling, loaded on first use and kept beside H3."""
        if self._seedvr2 is None:
            model = self.nodes.UNETLoader().load_unet(SEEDVR2_UNET, "default")[0]
            vae = self.nodes.VAELoader().load_vae(SEEDVR2_VAE)[0]
            self._seedvr2 = (model, vae)
        return self._seedvr2

    def upscale_video(self, *, source_path, width, height, seed, video_path, thumb_path, on_progress):
        """Upscale a finished video to width×height with SeedVR2, keeping its audio and frame rate."""
        import torch
        from comfy_api.latest import InputImpl
        from comfy_extras.nodes_seedvr import (
            SeedVR2Conditioning, SeedVR2PostProcessing, SeedVR2Preprocess, SeedVR2TemporalChunk, SeedVR2TemporalMerge,
        )

        self._cancel = False
        self.mm.interrupt_current_processing(False)
        timings = {}

        def stage(name):
            on_progress(name, 0.0)
            timings[name] = time.perf_counter()

        try:
            with torch.inference_mode():
                if self._seedvr2 is None:
                    stage("loading")
                model, vae = self._seedvr2_models()
                stage("reading")
                source = InputImpl.VideoFromFile(str(source_path)).get_components()
                count = source.images.shape[0]
                resized = self.utils.common_upscale(source.images.movedim(-1, 1), width, height, "lanczos",
                                                    "disabled").movedim(1, -1)
                padded = SeedVR2Preprocess.execute(resized_images=resized)[0]
                latent = self.nodes.VAEEncode().encode(vae, padded)[0]
                chunks, overlap = SeedVR2TemporalChunk.execute(
                    latent=latent, temporal_overlap=UPSCALE["overlap"], chunking_mode={"chunking_mode": "auto"})
                self._check()

                stage("upscaling")
                sampled = []
                for i, chunk in enumerate(chunks):
                    positive, negative = SeedVR2Conditioning.execute(model=model, vae_conditioning=chunk)
                    sampled.append(self.nodes.KSampler().sample(
                        model, seed, UPSCALE["steps"], UPSCALE["cfg"], UPSCALE["sampler"], UPSCALE["scheduler"],
                        positive, negative, chunk, denoise=1.0)[0])
                    on_progress("upscaling", (i + 1) / len(chunks))
                    self._check()
                merged = sampled[0] if len(sampled) == 1 else \
                    SeedVR2TemporalMerge.execute(latents=sampled, temporal_overlap=[overlap])[0]

                stage("decoding")
                images = self.nodes.VAEDecode().decode(vae, merged)[0]
                images = SeedVR2PostProcessing.execute(images=images, original_resized_images=resized,
                                                       color_correction_method=UPSCALE["color"])[0]
                images = images.reshape(-1, *images.shape[-3:])[:count]
                self._check()

                stage("saving")
                video = self.n["CreateVideo"].execute(images, float(source.frame_rate), source.audio)[0]
                video.save_to(str(video_path), format=self.Types.VideoContainer("mp4"),
                              codec=self.Types.VideoCodec("auto"))
                self._save_thumb(images[images.shape[0] // 2], thumb_path)
        except self.mm.InterruptProcessingException:
            raise Canceled()
        finally:
            self.mm.interrupt_current_processing(False)

        end = time.perf_counter()
        names = list(timings)
        durations = {n: round((timings[names[i + 1]] if i + 1 < len(names) else end) - timings[n], 1)
                     for i, n in enumerate(names)}
        return {"frames": int(images.shape[0]), "chunks": len(chunks), "steps": UPSCALE["steps"],
                "timings": durations, "models": upscale_model_info()}

    @staticmethod
    def _save_mp3(audio, path):
        """Encode the waveform as VBR mp3 V0 with PyAV, as ComfyUI's SaveAudioAdvanced does in the template."""
        import av
        wave = audio["waveform"][0].float().cpu()
        rate = audio["sample_rate"]
        layout = "mono" if wave.shape[0] == 1 else "stereo"
        with av.open(str(path), mode="w", format="mp3") as container:
            stream = container.add_stream("libmp3lame", rate=rate, layout=layout)
            stream.codec_context.qscale = 1
            frame = av.AudioFrame.from_ndarray(wave.movedim(0, 1).reshape(1, -1).numpy(), format="flt", layout=layout)
            frame.sample_rate = rate
            frame.pts = 0
            container.mux(stream.encode(frame))
            container.mux(stream.encode(None))

    @staticmethod
    def _save_picture(frame, path):
        import numpy as np
        from PIL import Image

        pixels = (frame.clamp(0, 1).cpu().float().numpy() * 255).round().astype(np.uint8)
        Image.fromarray(pixels).save(path)

    @staticmethod
    def _save_thumb(frame, path):
        import numpy as np
        from PIL import Image

        pixels = (frame.clamp(0, 1).cpu().float().numpy() * 255).round().astype(np.uint8)
        img = Image.fromarray(pixels)
        img.thumbnail((640, 640))
        img.save(path, quality=85)
