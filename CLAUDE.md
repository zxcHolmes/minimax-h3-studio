# CLAUDE.md

## Overview

MiniMax-H3 Studio: a MiniMax-H3 video generation service that **does not need the ComfyUI UI**. It is deployed to a single GPU machine and used from a browser.

- `comfy_launcher/`: headless launcher. Uses ComfyUI as a Python library and calls the nodes directly in the order of the official workflow, so it reuses ComfyUI's quantized checkpoints (int8 DiT, nvfp4 text encoder) and DynamicVRAM memory management. Output is **pixel-identical** to the official ComfyUI workflow (PSNR inf).
- `server/`: resident HTTP server. Weights load once, one job runs at a time, with a job queue and a sqlite record.
- `web/`: Vue 3 frontend with four modes: text to video, image to video (first frame / first + last frame), reference images (Ref2VA) and picture generation (MOSS-Image, mode t2i).
- `deploy.sh`: one-command deploy to the GPU machine; also downloads models remotely (`./deploy.sh models`).
- `scripts/prepare_models.py`: downloads every model the server uses (base models, text encoders, VAEs, LoRAs, MOSS-Image) into `$H3_COMFYUI/models`.

Deployment settings come from environment variables. Locally they live in `.env` (git-ignored); `.env.example` is the documented template. When adding a setting, update both `.env.example` and the configuration table in the README.

## Environment

- The GPU machine needs a ComfyUI checkout with MiniMax-H3 support (developed against 0.42). The server and launcher reuse ComfyUI's Python environment (conda or venv).
- The timings in the tables were measured on an RTX 4090 24GB with 125GB RAM and torch cu128. On cu128 the comfy-kitchen CUDA ops are unavailable.
- When killing processes over ssh, use the bracket form `pkill -f "[m]ain.py ..."`, otherwise the pattern matches and kills the ssh session itself.

## Models and LoRAs (measured findings)

Shared components (under `$H3_COMFYUI/models/`):

| Component | File |
|---|---|
| FL2VA base (text / image / first + last frame) | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` |
| Ref2VA base (reference images) | `minimax_h3_ref2va_pruned_int8_convrot.safetensors` |
| Text encoder | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| VAE | `minimax_h3_video_vae_fp16` + `minimax_h3_audio_vae_fp32` |

Resolution (`RESOLUTIONS`: 544p = 960×544 pixel area, 768p = 1344×768 pixel area) and LoRA are independent choices. The base model follows the mode: jobs with reference images use ref2va, everything else uses fl2va. LoRAs are defined in `LORAS` in `server/h3_engine.py`; the recommended default per mode and resolution is in `DEFAULT_LORAS`:

| LoRA key | Base | File | Steps | Shift | Resolutions | 5 s clip |
|---|---|---|---|---|---|---|
| `lightx2v-8step-v1.0` (544p default) | fl2va | `fl2v_turbo_8step_v1.0` | 8 | 12/3 | 544p | ~60s |
| `lightx2v-4step-v1.3` (768p default) | fl2va | `fl2v_turbo_4step_v1.3_768p` | 4 | 6/3 | 768p | ~80s |
| `larryvrh-v4` | fl2va | `minimax_h3_turbo_v4_step600_ema` | 4 | 12/3 | 544p / 768p | ~40s / ~82s |
| `lightx2v-ref-v0.1` (reference 544p default) | ref2va | `ref2v_turbo_4step_v0.1` | 4 | 12/3 | 544p / 768p | ~45s / ~100s |
| `lightx2v-ref-v1.0` (reference 768p default) | ref2va | `ref2v_turbo_4step_v1.0_768p` | 4 | 12/3 | 768p | ~100s |

FastH3 (FastVideo's distilled 8-step bases) is a second model group (`GROUPS` in `h3_engine.py`). Its `LORAS` entries have `group: "fasth3"`, their own `unet` (+ `unet_source`), `file: None`, `loader: "none"`, a `sampler` and `vsa` settings:

| Key | Family | Base file | Sampler | Shift | VSA keep / start |
|---|---|---|---|---|---|
| `fasth3-v2` | fl2va | `fastvideo_fasth3_8step_v2_pruned_int8_convrot` | res_multistep | 10/3 | 10 / 0.2 |
| `fasth3-omniref` | ref2va | `fasth3_omniref_8step_pruned_int8_convrot` | euler | 12/3 | 10 / 0 |

VSA needs comfy kitchen attention; on the GPU box comfy_kitchen 0.2.39 was rebuilt for CUDA 12.8 (sm_89), because the cu13 wheel crashes on driver 570. FastH3 is not faster than the LoRAs on the 4090; OmniRef's gain is 768p reference shots without the green glow.

Adding a LoRA only takes one entry in `LORAS` (with `source` set to its HF repo): the frontend picks it up through `/api/presets` and `prepare_models.py` downloads it. The base models, text encoder and VAEs all come from `Comfy-Org/MiniMax-H3`.

- Sampling uses the simple scheduler + BasicGuider (no CFG). The sampler is euler, except larryvrh, which uses its own turbo sampler.
- The shift must match the LoRA. 6/3 for 768p v1.3 is the official LightX2V config. ref2v LoRAs need 12; at 6, moving subjects smear into colour blobs.
- Reference mode at 768p sometimes puts a green banded glow on a subject; 544p does not, so 544p is the recommended reference resolution.
- The flags `--enable-triton-backend --use-sage-attention` make generation about 2× faster with no visible quality loss (on by default in the server). The w4a8 base is slower than int8.
- The larryvrh LoRA (`minimax_h3_turbo_v4_step600_ema`) needs its own nodes `MiniMaxH3TurboLoRA` + `MiniMaxH3TurboSampler` and shift 12. Its entry has `loader: "larryvrh"`, which makes the engine load those nodes from `custom_nodes/ComfyUI-MiniMax-H3-Turbo`. It loses subject identity in reference mode, so it is offered for fl2va only.
- Frame counts snap to the 17k+5 grid at 24 fps, e.g. 5 seconds is 124 frames.
- Image-to-video prompts need keyframe tags: `<Picture 1>` refers to the first frame and `<Picture 2>` to the last frame. The server adds them with `with_keyframe_prefix` when missing.
- Reference-mode prompts follow the official ref2va layout: subject_definitions / summary / retention_analysis / detailed_description / overall_soundscape / non_diegetic_music. The frontend assembles these sections from the reference images and their subject descriptions.

## Key files

- `comfy_launcher/run_h3.py`: headless launcher for single runs or batches via `--jobs-json`.
  - `bootstrap_comfy()` replicates the process-level setup of ComfyUI's `main.py`: argument parsing, cuda_malloc, `comfy_aimdo.control.init`, `init_devices`, and setting `CoreModelPatcher` to `ModelPatcherDynamic`. Without this DynamicVRAM step it runs out of memory.
  - Nodes are always called with keyword arguments, because ComfyUI reorders node signature parameters between releases.
  - `--lora-loader larryvrh` loads larryvrh's custom nodes. Arguments after `--` are passed through to ComfyUI.
- `comfy_launcher/bench.sh`: wraps run_h3.py, records peak VRAM with nvidia-smi and uses `flock gpu.lock` to run tests one at a time.
- `comfy_launcher/prompts_*.json`: test prompts.
- `scripts/prepare_models.py`: standard library only, runs with any python3. The file list is built from `UNETS`, `CLIP`, the VAE constants, the `MOSS_*` constants and `LORAS` in `h3_engine.py`; existing files are skipped, `.part` files allow resuming, and `HF_ENDPOINT` selects a mirror. ComfyUI itself and the larryvrh custom node are cloned by the user, not by this script.
- `server/h3_engine.py`: resident engine.
  - The text encoder and VAEs stay loaded. Only one base DiT is resident at a time (H3 fl2va / ref2va or a FastH3 base, see `unet_file()`); `_use_base()` unloads the old base before loading the new one. Because DynamicVRAM streams weights from mmap, a switch takes under a second.
  - Each model choice is a ModelPatcher clone of the resident base carrying its own LoRA (if any), SigmaShift, sampler and attention patches. It is created on first use and cached until the base switches, so switching LoRAs on the same base does not reload the base.
  - `generate()` and `generate_image()` must only be called from the worker thread.
  - Pictures: `generate_image()` runs MOSS-Image with the ComfyUI template settings (`IMAGE`: 25 steps, cfg 2.5, er_sde, simple, the template's negative prompt; ~1 MP sizes from `image_size()`). The MOSS UNET, text encoder (CLIPLoader type `moss_image`) and VAE load lazily on the first picture job and stay loaded next to the H3 models; DynamicVRAM moves weights as needed. The template's prompt expansion (TextGenerate) is left out: it took ~45 s and made results worse.
- `server/h3_jobs.py`: sqlite job store with a thread lock. The `result` and `refs` columns hold JSON. New columns get an ALTER TABLE migration in `__init__`.
- `server/app.py`: aiohttp server.
  - A worker thread loads the models and runs jobs one at a time in FIFO order.
  - Endpoints: `/api/health`, `/api/presets`, `GET/POST /api/jobs`, `/api/jobs/{id}`, `POST /api/jobs/{id}/cancel`, `DELETE /api/jobs/{id}`. Static files are under `/files/{videos,pictures,thumbs,uploads}`; every other path goes to the frontend.
  - `POST /api/jobs` takes a multipart form: `prompt`, `resolution` (544p / 768p), `lora` (optional; defaults to the recommended LoRA; the server checks that its base family and resolution match), `lora_strength` (0–2, default 1; stored in the `lora_strength` column and recorded in `result.models`; the engine caches clones per (LoRA, strength) and keeps only the latest non-1.0 strength), `duration` (2–15 s), `seed`, `aspect_ratio` (`image` follows the input picture's ratio), `image`, `last_image`, `ref_image` (up to 6, repeatable). The job mode is one of t2v / i2v / fl2v / r2v. A form with `kind=image` creates a t2i picture job instead (`prompt`, `aspect_ratio`, `seed`); no input images, resolution or LoRA, and the PNG name goes in the `picture` column.
  - `/api/presets` returns `resolutions`, `groups`, `loras` (each with `group`), `default_loras` and `image` (picture sizes per aspect ratio and the MOSS models). The job's `preset` column holds the resolution and the `lora` column the LoRA key; old combined ids such as `ref-544p` are migrated at startup by `backfill_lora(LEGACY_PRESETS)`.
  - LoRAs and jobs carry a `models` field (base, LoRA, sampler, shift) for the frontend to display. Finished jobs read the models they actually ran on from `result.models`, so later LoRA config changes do not relabel old jobs.
  - index.html is re-read on every request, so a frontend-only deploy needs no restart.
- `server/h3-server.service.in`: systemd unit template. `deploy.sh` replaces placeholders such as `@USER@` and `@DIR@` with values from `.env` before installing it; the unit activates ComfyUI's Python environment and then runs `app.py`.
- `web/src/components/GenerateForm.vue`: generation form. The prompt is edited in picture / sound / music sections, or as the raw prompt; also resolution, model group (MiniMax-H3 + LoRA or FastH3), model choice (filtered by group, mode and resolution, recommended one marked), aspect ratio, duration ruler, seed and reuse. The Picture tab has its own prompt, aspect ratio and Expand prompt toggle; `useAsRef` / `useAsFrame` take a finished picture into the Reference or Frames mode.
- `web/src/components/RefImages.vue`: reference image list, each image with a subject description. Image N is `<Subject N>` / `<Picture N>`.
- `web/src/components/ImageDrop.vue`: drag-and-drop upload for the first / last frame.
- `web/src/components/JobCard.vue`: job card with progress, video or picture, reuse button, and Reference / Frame buttons on pictures; the prompt is clamped to three lines with a Show more toggle.
- `doc/animated-short-workflow.md`: the agent workflow for making an animated series through the API (character bible, casting clips as references, storyboards, QC, ffmpeg assembly). Follow it when asked to make a multi-shot or multi-episode video.
- `web/src/style.css`: design tokens, with light and dark sets.

## Deployment

```bash
./deploy.sh          # frontend + server (restarts the service)
./deploy.sh web      # frontend only; no restart, loaded weights are unaffected
./deploy.sh server   # server only (restarts the service)
./deploy.sh models   # download models on the GPU machine; extra arguments go to prepare_models.py
FORCE=1 ./deploy.sh server   # restart even while jobs are running or queued (they are lost)
```

- The frontend is built locally with `npm run build`; dist is copied with scp to `web_dist.new` and swapped in atomically.
- `deploy.sh` reads `.env` first; environment variables already set on the command line take precedence over `.env`. Each setting is documented in `.env.example`.
- The server code (`server/` and `comfy_launcher/run_h3.py`) is rsynced to `$H3_DEPLOY_DIR` (default: the remote user's `~/minimax-h3-studio`); then the systemd unit is rendered, installed and restarted, and `/api/health` is polled until the state is ready.
- URL: `http://<host of H3_DEPLOY_HOST>:<H3_PORT>`
- Data directory on the server: `$H3_DEPLOY_DIR/data/`, containing `jobs.db`, `videos/`, `pictures/`, `thumbs/`, `uploads/`.
- Logs: `ssh $H3_DEPLOY_HOST journalctl -u h3-server -f`
- Environment variables read by the server process: `H3_COMFYUI` (required), `H3_DATA`, `H3_WEB_DIST`, `H3_HOST`/`H3_PORT`, `H3_COMFY_ARGS`.

## Local development

```bash
cd web && npm install && npm run dev   # vite reads the root .env and proxies /api and /files to H3_API (default: the deployed machine)
```

For comparison tests, stop the service first (`sudo systemctl stop h3-server`) to free the GPU, copy `comfy_launcher/` to the GPU machine, set `H3_COMFYUI` inside ComfyUI's Python environment, and run bench.sh:

```bash
./bench.sh <name> --jobs-json prompts_stylized.json --steps 4 --width 960 --height 544 \
  --shift-video 12 --lora <lora>.safetensors -- --enable-triton-backend --use-sage-attention
```

Results land in `out_<name>/` and can be rsynced to a local `outputs/` (git-ignored). Afterwards run `sudo systemctl start h3-server`, or simply rerun `./deploy.sh`.
