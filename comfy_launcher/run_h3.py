"""Headless MiniMax-H3 Turbo launcher that reuses ComfyUI as a Python library.

No server, no UI, no workflow JSON: the nodes of the official example graph
are called directly in order, so ComfyUI's quantized checkpoints (int8 / w4a8
DiT, nvfp4 Qwen3-VL text encoder) and its dynamic VRAM offload are used as-is.

Example:
    python run_h3.py --comfyui /path/to/ComfyUI \
        --prompt "integrated_multimodal_description: ..." \
        --lora minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors \
        --steps 8 --width 960 --height 544 --duration 5

Arguments after `--` are forwarded to ComfyUI's own CLI parser
(e.g. `-- --reserve-vram 2`).
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path


def parse_args():
    argv = sys.argv[1:]
    comfy_argv = []
    if "--" in argv:
        split = argv.index("--")
        argv, comfy_argv = argv[:split], argv[split + 1:]

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--comfyui", default=os.environ.get("H3_COMFYUI") or os.environ.get("COMFYUI_PATH"),
                   required=not (os.environ.get("H3_COMFYUI") or os.environ.get("COMFYUI_PATH")),
                   help="ComfyUI checkout (default: $H3_COMFYUI or $COMFYUI_PATH)")
    p.add_argument("--prompt", help="Prompt text (or use --prompt-file / --jobs-json)")
    p.add_argument("--prompt-file", type=Path)
    p.add_argument("--jobs-json", type=Path, help="Repo-style examples/prompts_*.json; runs every example")
    p.add_argument("--limit", type=int, default=None, help="Only run the first N jobs of --jobs-json")
    p.add_argument("--first-frame", type=Path, help="I2VA / FL2VA first frame")
    p.add_argument("--last-frame", type=Path, help="FL2VA last frame")
    p.add_argument("--ref-image", type=Path, action="append", default=[], help="Ref2VA reference image (repeatable)")
    p.add_argument("--ref-image-size", choices=["match", "max"], default="match")
    p.add_argument("--width", type=int, default=960)
    p.add_argument("--height", type=int, default=544)
    p.add_argument("--duration", type=float, default=5.0, help="Seconds; snapped up to the 17k+5 frame grid")
    p.add_argument("--unet", default=None, help="Diffusion model in models/diffusion_models (default depends on task)")
    p.add_argument("--clip", default="qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")
    p.add_argument("--vae", default="minimax_h3_video_vae_fp16.safetensors")
    p.add_argument("--audio-vae", default="minimax_h3_audio_vae_fp32.safetensors")
    p.add_argument("--lora", default="minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
                   help="LoRA in models/loras; pass 'none' for the base model")
    p.add_argument("--lora-strength", type=float, default=1.0)
    p.add_argument("--lora-loader", choices=["core", "larryvrh"], default="core",
                   help="core: ComfyUI LoraLoaderModelOnly (lightx2v LoRAs, as in the official workflows); "
                        "larryvrh: custom_nodes/ComfyUI-MiniMax-H3-Turbo LoRA node + its 4-step sampler")
    p.add_argument("--steps", type=int, default=8)
    p.add_argument("--shift-video", type=float, default=12.0)
    p.add_argument("--shift-audio", type=float, default=3.0)
    p.add_argument("--sampler", default="euler")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output-dir", type=Path, default=Path("outputs"))
    args = p.parse_args(argv)
    return args, comfy_argv


def bootstrap_comfy(comfyui_path, comfy_argv):
    """Replicate the parts of ComfyUI's main.py that matter for inference."""
    sys.path.insert(0, str(comfyui_path))
    os.chdir(comfyui_path)
    sys.argv = [sys.argv[0], *comfy_argv]

    import comfy.options
    comfy.options.enable_args_parsing()
    from comfy.cli_args import args as comfy_args, enables_dynamic_vram

    import cuda_malloc  # noqa: F401  (sets the CUDA allocator backend before torch init)
    import comfy_aimdo.control
    if enables_dynamic_vram():
        headroom = None if comfy_args.reserve_vram is None else int(comfy_args.reserve_vram * 1024 ** 3)
        comfy_aimdo.control.init(simple_vram_headroom=headroom, nvml_pressure=not comfy_args.disable_nvml_pressure)

    from app.logger import setup_logger
    setup_logger(log_level="INFO")

    import utils.extra_config
    extra = os.path.join(comfyui_path, "extra_model_paths.yaml")
    if os.path.isfile(extra):
        utils.extra_config.load_extra_path_config(extra)

    # Second half of the DynamicVRAM setup in main.py: without it the legacy
    # ModelPatcher keeps the whole DiT resident and a 24 GB card OOMs.
    import comfy.memory_management
    import comfy.model_management
    import comfy.model_patcher
    if enables_dynamic_vram() and comfy.model_management.is_nvidia():
        devices = comfy.model_management.get_all_torch_devices()
        try:
            ok = comfy_aimdo.control.init_devices((d.index, int(comfy_args.vram_headroom * 1024 ** 3)) for d in devices)
        except TypeError:
            ok = comfy_aimdo.control.init_devices(d.index for d in devices)
        if ok:
            comfy_aimdo.control.set_log_warning()
            comfy.model_patcher.CoreModelPatcher = comfy.model_patcher.ModelPatcherDynamic
            comfy.memory_management.aimdo_enabled = True
            print("DynamicVRAM enabled", flush=True)
        else:
            print("WARNING: comfy-aimdo init failed; DynamicVRAM disabled", flush=True)


def load_larryvrh_nodes(comfyui_path):
    import importlib.util
    init = Path(comfyui_path) / "custom_nodes" / "ComfyUI-MiniMax-H3-Turbo" / "__init__.py"
    spec = importlib.util.spec_from_file_location("minimax_h3_turbo_nodes", init)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_image(path):
    import numpy as np
    import torch
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return torch.from_numpy(np.asarray(img).astype(np.float32) / 255.0)[None]


def build_jobs(args):
    if args.jobs_json is not None:
        data = json.loads(args.jobs_json.read_text())
        examples = data["examples"] if isinstance(data, dict) else data
        base = args.jobs_json.parent
        jobs = []
        for ex in examples[: args.limit]:
            raw_images = ex.get("images") or ([ex["image"]] if ex.get("image") else [])
            images = [base / p for p in raw_images]
            refs = [base / (r["path"] if isinstance(r, dict) else r) for r in ex.get("references", [])]
            jobs.append({
                "prompt": ex["prompt"],
                "first": images[0] if len(images) >= 1 else None,
                "last": images[1] if len(images) >= 2 else None,
                "refs": refs,
                "duration": ex.get("duration", args.duration),
            })
        return jobs

    prompt = args.prompt if args.prompt is not None else args.prompt_file.read_text()
    return [{
        "prompt": prompt,
        "first": args.first_frame,
        "last": args.last_frame,
        "refs": args.ref_image,
        "duration": args.duration,
    }]


class Timer:
    def __init__(self):
        self.stages = {}

    def __call__(self, name):
        timer = self

        class _Ctx:
            def __enter__(self):
                import torch
                torch.cuda.synchronize()
                self.t0 = time.perf_counter()

            def __exit__(self, *exc):
                import torch
                torch.cuda.synchronize()
                dt = time.perf_counter() - self.t0
                timer.stages[name] = timer.stages.get(name, 0.0) + dt
                print(f"[time] {name}: {dt:.1f}s", flush=True)

        return _Ctx()


def main():
    args, comfy_argv = parse_args()
    if args.prompt is None and args.prompt_file is None and args.jobs_json is None:
        sys.exit("one of --prompt / --prompt-file / --jobs-json is required")
    for attr in ("prompt_file", "jobs_json", "first_frame", "last_frame", "output_dir"):
        value = getattr(args, attr)
        if value is not None:
            setattr(args, attr, value.expanduser().resolve())
    args.ref_image = [p.expanduser().resolve() for p in args.ref_image]
    jobs = build_jobs(args)
    is_ref = any(job["refs"] for job in jobs)
    if args.unet is None:
        args.unet = ("minimax_h3_ref2va_pruned_int8_convrot.safetensors" if is_ref
                     else "minimax_h3_fl2va_pruned_int8_convrot.safetensors")

    bootstrap_comfy(args.comfyui, comfy_argv)

    import torch
    import nodes
    from comfy_extras.nodes_audio import VAEDecodeAudio
    from comfy_extras.nodes_custom_sampler import (
        BasicGuider, BasicScheduler, KSamplerSelect, RandomNoise, SamplerCustomAdvanced,
    )
    from comfy_extras.nodes_minimax_h3 import (
        MiniMaxH3ImageToVideo, MiniMaxH3ReferenceToVideo, MiniMaxH3SigmaShift,
    )
    from comfy_extras.nodes_video import CreateVideo
    from comfy_api.latest import Types

    timer = Timer()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with torch.inference_mode():
        with timer("load_models"):
            model = nodes.UNETLoader().load_unet(args.unet, "default")[0]
            model = MiniMaxH3SigmaShift.execute(model, args.shift_video, args.shift_audio)[0]
            if args.lora.lower() == "none":
                pass
            elif args.lora_loader == "larryvrh":
                turbo = load_larryvrh_nodes(args.comfyui)
                model = turbo.MiniMaxH3TurboLoRA().apply_lora(model, args.lora, args.lora_strength)[0]
            else:
                model = nodes.LoraLoaderModelOnly().load_lora_model_only(model, args.lora, args.lora_strength)[0]
            clip = nodes.CLIPLoader().load_clip(args.clip, "minimax", "default")[0]
            vae = nodes.VAELoader().load_vae(args.vae)[0]
            audio_vae = nodes.VAELoader().load_vae(args.audio_vae)[0]
            if args.lora_loader == "larryvrh":
                sampler = turbo.MiniMaxH3TurboSampler().get_sampler()[0]
            else:
                sampler = KSamplerSelect.execute(args.sampler)[0]
            sigmas = BasicScheduler.execute(model, "simple", args.steps, 1.0)[0]

        for index, job in enumerate(jobs):
            seed = args.seed + index
            length = max(5, round(job["duration"] * 24))
            print(f"\n=== job {index}: {args.width}x{args.height} {job['duration']}s seed={seed} "
                  f"steps={args.steps} lora={args.lora}", flush=True)
            torch.cuda.reset_peak_memory_stats()
            job_start = time.perf_counter()

            with timer("text_encode"):
                if job["refs"]:
                    refs = {f"ref_image_{i}": load_image(p) for i, p in enumerate(job["refs"], 1)}
                    # Keyword arguments: the positional order changed between ComfyUI releases.
                    cond, latent = MiniMaxH3ReferenceToVideo.execute(
                        clip=clip, vae=vae, audio_vae=audio_vae, prompt=job["prompt"],
                        width=args.width, height=args.height, length=length,
                        ref_image_size=args.ref_image_size, ref_images=refs)
                else:
                    cond, latent = MiniMaxH3ImageToVideo.execute(
                        clip=clip, vae=vae, prompt=job["prompt"], width=args.width,
                        height=args.height, length=length,
                        first_frame=load_image(job["first"]) if job["first"] else None,
                        last_frame=load_image(job["last"]) if job["last"] else None)

            with timer("sampling"):
                guider = BasicGuider.execute(model, cond)[0]
                noise = RandomNoise.execute(seed)[0]
                samples = SamplerCustomAdvanced.execute(noise, guider, sampler, sigmas, latent)[0]

            with timer("vae_decode"):
                images = nodes.VAEDecode().decode(vae, samples)[0]
                audio = VAEDecodeAudio.execute(audio_vae, samples)[0]

            out = args.output_dir / f"{index:04d}_seed{seed}.mp4"
            video = CreateVideo.execute(images, 24.0, audio)[0]
            video.save_to(str(out), format=Types.VideoContainer("mp4"), codec=Types.VideoCodec("auto"))

            total = time.perf_counter() - job_start
            peak = torch.cuda.max_memory_allocated() / 1024 ** 3
            print(f"[done] {out}  frames={images.shape[0]}  job_time={total:.1f}s  "
                  f"torch_peak_vram={peak:.1f}GB", flush=True)

    print("\n[summary] cumulative stage times:", {k: round(v, 1) for k, v in timer.stages.items()})


if __name__ == "__main__":
    main()
