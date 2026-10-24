# CLAUDE.md

## Overview

MiniMax-H3 Studio: a MiniMax-H3 video generation service that **does not need the ComfyUI UI**. It is deployed to a single GPU machine and used from a browser.

- `comfy_launcher/`: headless launcher. Uses ComfyUI as a Python library and calls the nodes directly in the order of the official workflow, so it reuses ComfyUI's quantized checkpoints (int8 DiT, nvfp4 text encoder) and DynamicVRAM memory management. Output is **pixel-identical** to the official ComfyUI workflow (PSNR inf).
- `server/`: resident HTTP server. Weights load once, one job runs at a time, with a job queue and a sqlite record.
- `web/`: Vue 3 frontend with five modes: text to video, image to video (first frame / first + last frame), reference images and videos (Ref2VA), picture generation (MOSS-Image, mode t2i) and music generation (MiniMax Music 3, mode t2m). Finished videos can be upscaled with FlashVSR v1.1 or SeedVR2 (mode upscale).
- `deploy.sh`: one-command deploy to the GPU machine; also downloads models remotely (`./deploy.sh models`).
- `scripts/prepare_models.py`: downloads every model the server uses (base models, text encoders, VAEs, LoRAs, MOSS-Image, MiniMax Music 3, SeedVR2, FlashVSR) into `$H3_COMFYUI/models`.

Deployment settings come from environment variables. Locally they live in `.env` (git-ignored); `.env.example` is the documented template. When adding a setting, update both `.env.example` and the configuration table in the README.

## Environment

- The GPU machine needs a ComfyUI checkout with MiniMax-H3 support (developed against 0.42). The server and launcher reuse ComfyUI's Python environment (conda or venv).
- The timings in the tables were measured on an RTX 4090 24GB with 125GB RAM and torch cu128. comfy_kitchen 0.2.39 is built from source for CUDA 12.8 / sm_89 on the GPU box (the cu13 wheel's CUDA ops do not load there), Stock ComfyUI's `comfy/quant_ops.py` calls `ck.registry.disable("cuda")` whenever torch is older than cu130, which left that build unused. The GPU box's ComfyUI carries a local patch (original in `comfy/quant_ops.py.orig`) that only disables the CUDA backend when its ops fail to load, so the server now runs with both the CUDA and the triton backends (startup log: `backend cuda: ... 'disabled': False`). Measured: a 12.3 s 544p larryvrh shot went from 108 s to 90 s. Re-apply the patch after updating ComfyUI (`git pull` may conflict with it). The full rebuild (cu128, sm_89, build script in `~/build/build_kitchen.sh` on the GPU box), install, patch and verification steps are in the README section "comfy_kitchen on PyTorch older than cu130". The `int8_tensorwise` + convrot checkpoints run their linear layers through `comfy_kitchen.int8_linear` (row-wise dynamic activation quantization + int8 matmul); `--enable-triton-backend` is still needed, because without kitchen's accelerated backends int8 matmul falls back to eager (the flag alone gave ~2× before the patch).
- When killing processes over ssh, use the bracket form `pkill -f "[m]ain.py ..."`, otherwise the pattern matches and kills the ssh session itself.

## Models and LoRAs (measured findings)

Shared components (under `$H3_COMFYUI/models/`):

| Component | File |
|---|---|
| FL2VA base (text / image / first + last frame) | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` |
| Text encoder | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| VAE | `minimax_h3_video_vae_int8_convrot` (as in every official H3 template) + `minimax_h3_audio_vae_fp32` |

Resolution (`RESOLUTIONS`: 544p = 960×544 pixel area, 768p = 1344×768 pixel area) and LoRA are independent choices. The base model follows the mode: reference jobs (ref2va family) run on FastH3 OmniRef only, everything else uses fl2va. LoRAs are defined in `LORAS` in `server/h3_engine.py`; the recommended default per mode and resolution is in `DEFAULT_LORAS`:

| LoRA key | Base | File | Steps | Shift | Resolutions | 5 s clip |
|---|---|---|---|---|---|---|
| `lightx2v-8step-v1.0` (544p default) | fl2va | `fl2v_turbo_8step_v1.0` | 8 | 12/3 | 544p | ~45s |
| `lightx2v-4step-v1.3` (768p default) | fl2va | `fl2v_turbo_4step_v1.3_768p` | 4 | 6/3 | 768p | ~64s |
| `larryvrh-v4` | fl2va | `minimax_h3_turbo_v4_step600_ema` | 4 | 12/3 | 544p / 768p | ~31s / ~67s |

FastH3 (FastVideo's distilled 8-step bases) is a second model group (`GROUPS` in `h3_engine.py`). Its `LORAS` entries have `group: "fasth3"`, their own `unet` (+ `unet_source`), `file: None`, `loader: "none"`, a `sampler` and `vsa` settings:

| Key | Family | Base file | Sampler | Shift | VSA keep / start |
|---|---|---|---|---|---|
| `fasth3-v2` | fl2va | `fastvideo_fasth3_8step_v2_pruned_int8_convrot` | res_multistep | 10/3 | 10 / 0.2 |
| `fasth3-omniref` (reference default) | ref2va | `fasth3_omniref_8step_pruned_int8_convrot` | euler | 12/3 | 10 / 0 |

VSA needs comfy kitchen attention; on the GPU box comfy_kitchen 0.2.39 was rebuilt for CUDA 12.8 (sm_89), because the cu13 wheel crashes on driver 570. With the kitchen CUDA backend enabled (see Environment) a 5 s FastH3 clip takes ~39 s / ~71 s (V2, 544p / 768p) and ~41 s / ~67 s (OmniRef): faster than the 8-step LoRA, slower than the 4-step ones at 544p, about the same at 768p. The H3 + ref2v LoRA route (ref2va base + lightx2v `ref2v_turbo_4step` v0.1 / v1.0) was removed on 2026-10-23: on a fast sword-dance prompt it smeared moving sleeves and blades into comb-like streaks that read as dropped frames, at any sampler (euler / res_multistep) and still at 6–8 steps or strength 0.7, while OmniRef stayed clean at the same seed. The output was a true 24 fps / 260 frames; the stutter came from the per-frame smear. The 5 s timings in these tables were measured on 2026-10-22 after the kitchen patch (before it they were 17–48% slower).

Adding a LoRA only takes one entry in `LORAS` (with `source` set to its HF repo): the frontend picks it up through `/api/presets` and `prepare_models.py` downloads it. The base models, text encoder and VAEs all come from `Comfy-Org/MiniMax-H3`.

- Sampling uses the simple scheduler + BasicGuider (no CFG). The sampler is euler, except larryvrh, which uses its own turbo sampler.
- The shift must match the LoRA. 6/3 for 768p v1.3 is the official LightX2V config.
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
- `scripts/split_book.py`: splits an epub (OPF spine order) or txt (UTF-8 / GB18030) into one text file per chapter plus `chapters.json`, for `doc/novel-adaptation-workflow.md`. Standard library only, run with `python3 -I`.
- `scripts/prepare_models.py`: standard library only, runs with any python3. The file list is built from `UNETS`, `CLIP`, the VAE constants, the `MOSS_*` and `MUSIC_*` constants and `LORAS` in `h3_engine.py`; existing files are skipped, `.part` files allow resuming, and `HF_ENDPOINT` selects a mirror. ComfyUI itself and the larryvrh custom node are cloned by the user, not by this script.
- `server/h3_engine.py`: resident engine.
  - The text encoder and VAEs stay loaded. Only one base DiT is resident at a time (H3 fl2va / ref2va or a FastH3 base, see `unet_file()`); `_use_base()` unloads the old base before loading the new one. Because DynamicVRAM streams weights from mmap, a switch takes under a second.
  - Each model choice is a ModelPatcher clone of the resident base carrying its own LoRA (if any), SigmaShift, sampler and attention patches. It is created on first use and cached until the base switches, so switching LoRAs on the same base does not reload the base.
  - `generate()` and `generate_image()` must only be called from the worker thread.
  - Reference videos: `generate(ref_video_paths=)` passes them to `ReferenceToVideo` as `ref_videos` (their soundtracks as `ref_video_audios`). `_ref_video()` decodes the first `frame_count(duration)` frames at 24 fps and scales them down to the job's pixel area, plus the same stretch of the audio. The node itself would put every reference video on a 1344×768 canvas whatever the job's size, and the reference tokens join every attention call: ComfyUI's VSA keeps the whole packed prefix (text and references) exact for every query, unlike FastVideo, which trained OmniRef with each reference video as its own sparse region at keep 0.1. Measured on 2026-10-24 (FastH3 OmniRef, 4090): a 5 s 544p shot with a 5 s reference samples in ~100 s (~26 s without), 768p ~144 s, 15 s with a 15 s reference ~561 s; none ran out of memory. A 1080p reference at 544p took the same time as a 544p one. The motion, camera, timing and scene carry over closely when the prompt replaces a subject.
  - Guide audio: `generate(audio_path=, audio_start=)` loads the slice of the file that matches the shot (`_audio_clip()`, via ComfyUI's audio `load`) and chains `MiniMaxH3AddGuide(frame_idx=0, audio_vae=, audio=)` after ImageToVideo / ReferenceToVideo, so it works in every video mode. The anchored slice comes back nearly unchanged in the output audio.
  - Pictures: `generate_image()` runs MOSS-Image with the ComfyUI template settings (`IMAGE`: 25 steps, cfg 2.5, er_sde, simple, the template's negative prompt; ~1 MP sizes from `image_size()`). The MOSS UNET, text encoder (CLIPLoader type `moss_image`) and VAE load lazily on the first picture job and stay loaded next to the H3 models; DynamicVRAM moves weights as needed. The template's prompt expansion (TextGenerate) is left out: it took ~45 s and made results worse.
  - Music: `generate_music()` runs MiniMax Music 3 like the ComfyUI template (`MUSIC`): `MiniMaxMusic3TextEncode` (the text encoder autoregressively writes acoustic tokens; cfg_scale 1.7, top_k 50; its `seconds` output is the actual length, which can be shorter than `max_duration`), `ConditioningZeroOut` as negative, `EmptyMiniMaxMusic3LatentAudio`, KSampler 30 steps euler/simple cfg 1.7, `VAEDecodeAudioTiled` (1536/64). `_save_mp3()` writes VBR mp3 V0 with PyAV, because the system ffmpeg on the GPU box has no libmp3lame. int8 DiT and text encoder (CLIPLoader type `minimax`), loaded lazily and kept resident like MOSS. Stages: loading, composing, sampling, decoding, saving. Measured on the 4090: a 60 s song ~100 s (composing 68 s, sampling 28 s), 30 s ~60 s. The engine must run ComfyUI's per-node cleanup (`_after_node()`: `cleanup_prefetch_queues`, `reset_cast_buffers`, `vbars_reset_watermark_limits`) between music nodes and after the job: the AR text encoder records a per-thread CUDA malloc graph, and without the cleanup the second music job in the process fails with a device-side assert / CUBLAS error that poisons the CUDA context until restart.
  - Upscaling: `upscale_video()` runs SeedVR2 3B int8 like ComfyUI's `utility_seedvr2_3b_int8_upscale_video` template (`UPSCALE`): lanczos resize to `upscale_size()` (short side from `UPSCALE_TARGETS`), `SeedVR2Preprocess`, `VAEEncode`, KSampler 1 step euler/simple cfg 1 with `SeedVR2Conditioning`, `VAEDecode`, `SeedVR2PostProcessing` (color correction none). Unlike the template it splits the latent with `SeedVR2TemporalChunk` (auto, sized to free VRAM, overlap 2) and merges with `SeedVR2TemporalMerge`, so long or 1440p clips fit on 24 GB, and it uses the plain VAE nodes instead of the template's 512 px tiled ones: SeedVR2's VAE sizes its work from measured memory figures and runs whole frames when they fit, and the forced tiles nearly doubled the VAE time (a 10.8 s clip to 1080p: 510 s tiled, 272 s plain; the DiT is ~19 s of it). Audio and frame rate come from the source file. The models load lazily and stay resident.
  - FlashVSR: `flashvsr_video()` runs FlashVSR v1.1 (`FLASHVSR`: int8 ConvRot DiT, Tiny decoder, attention auto, which picks Triton block-sparse) through T8star's FlashVSR+ node (`custom_nodes/Comfyui-Flashvsr-Plus-T8`, commit `ac60d1e`; `_flashvsr_runtime()` imports its `flashvsr_plus` package and uses `ModelHandle` / `InferenceRequest`). It streams the source mp4 straight to the output mp4 (the node's default `Options`; source audio copied by its ffmpeg mux), with no ComfyUI VIDEO round trip; the canvas is padded to multiples of 128 and cropped back. The handle keeps the pipeline in CPU RAM between jobs. FlashVSR allocates with plain torch, outside ComfyUI's memory management, so `flashvsr_video()` first moves every ComfyUI model off the GPU (`unload_all_models`); without that, upscaling right after a video job ran out of memory with the H3 weights still resident. Measured: the same 10.8 s clip to 1080p in 87 s including the first load. Weights in `models/flashvsr_plus/` from `t8star/Flashvsr-Plus-Comfy`.
  - `POST /api/jobs/{id}/upscale` (form `upscaler` seedvr2 / flashvsr, `target`, optional `seed`) creates the job; the `source` column holds the source job id (the worker resolves its video file at run time) and `upscaler` the choice (NULL on old jobs means seedvr2).
- `server/h3_jobs.py`: sqlite job store with a thread lock. The `result` and `refs` columns hold JSON. New columns get an ALTER TABLE migration in `__init__`.
- `server/app.py`: aiohttp server.
  - A worker thread loads the models and runs jobs one at a time in FIFO order.
  - Endpoints: `/api/health`, `/api/presets`, `GET/POST /api/jobs`, `/api/jobs/{id}`, `POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/upscale`, `DELETE /api/jobs/{id}`, `POST /api/unload`. `/api/unload` (refused with 409 while a job runs or waits) runs `engine.unload()` on the worker thread through `Worker.call()`: it drops the base DiT, its clones and the lazy MOSS / music / SeedVR2 / FlashVSR models, unloads the rest from VRAM and empties the cache, so another program (e.g. faster-whisper) can use the GPU; the next job reloads what it needs and `/api/health` reports `unet: null` until then. Static files are under `/files/{videos,pictures,thumbs,uploads}`; every other path goes to the frontend.
  - `POST /api/jobs` takes a multipart form: `prompt`, `resolution` (544p / 768p), `lora` (optional; defaults to the recommended LoRA; the server checks that its base family and resolution match), `lora_strength` (0–2, default 1; stored in the `lora_strength` column and recorded in `result.models`; the engine caches clones per (LoRA, strength) and keeps only the latest non-1.0 strength), `sampler` (optional, one of `SAMPLERS` in `h3_engine.py`: euler / res_multistep / er_sde; empty or the model choice's own sampler stores NULL in the `sampler` column, and larryvrh and FastH3 (`fixed_sampling()`, set by `fixed` in `LORAS`) ignore it; the engine swaps only the KSampler, so no new model clone), `steps` (optional, `STEPS_RANGE` 1–30; the model choice's own count stores NULL in the `steps` column, and FastH3 ignores it; the engine rebuilds only the sigmas; API only, the form just shows the model choice's count), `duration` (2–15 s), `seed`, `aspect_ratio` (`image` follows the input picture's ratio), `image`, `last_image`, `ref_image` (up to 6, repeatable), `ref_video` (up to `MAX_REF_VIDEOS` 3, repeatable, at least 2 s; stored in the `ref_videos` JSON column, served as `ref_video_urls`; the prompt calls them `<Video k>` after the images, and their soundtracks `<Audio k>`), `audio` + `audio_start` (guide audio; stored in the `guide_audio` / `audio_start` columns, served as `guide_audio_url`). The job mode is one of t2v / i2v / fl2v / r2v; r2v (ref2va base) is chosen by reference images or videos or by a ref2va `lora`, so it also runs with zero references (the frontend then leaves out subject_definitions and retention_analysis). The form hides model groups with no choice for the mode (Reference shows FastH3 only) and gives the user's picked group back when they switch to a mode that has it. A form with `kind=image` creates a t2i picture job instead (`prompt`, `aspect_ratio`, `seed`); no input images, resolution or LoRA, and the PNG name goes in the `picture` column. `kind=music` creates a t2m job (`prompt` = caption, `lyrics`, `duration` 10–300 s as the maximum length, `seed`); lyrics go in the `lyrics` column and the mp3 name in `audio`.
  - `/api/presets` returns `resolutions`, `groups`, `loras` (each with `group` and `fixed`, which hides the sampler picker), `default_loras`, `samplers`, `steps_range`, `image` (picture sizes per aspect ratio and the MOSS models), `music` (length range and models) and `upscale` (targets and `upscalers` with their models). The job's `preset` column holds the resolution and the `lora` column the LoRA key; old combined ids such as `ref-544p` are migrated at startup by `backfill_lora(LEGACY_PRESETS)`.
  - LoRAs and jobs carry a `models` field (base, LoRA, sampler, shift) for the frontend to display. Finished jobs read the models they actually ran on from `result.models`, so later LoRA config changes do not relabel old jobs.
  - index.html is re-read on every request, so a frontend-only deploy needs no restart.
- `server/h3-server.service.in`: systemd unit template. `deploy.sh` replaces placeholders such as `@USER@` and `@DIR@` with values from `.env` before installing it; the unit activates ComfyUI's Python environment and then runs `app.py`.
- `web/src/components/GenerateForm.vue`: generation form. The prompt is edited in picture / sound / music sections, or as the raw prompt; also resolution, model group (MiniMax-H3 + LoRA or FastH3), model choice (filtered by group, mode and resolution, recommended one marked), aspect ratio, duration ruler, seed and reuse. The Picture tab has its own prompt, aspect ratio and Expand prompt toggle; `useAsRef` / `useAsFrame` take a finished picture into the Reference or Frames mode; video modes have an optional guide audio with a start time, and `useAsAudio` takes a finished song into it. The Music tab has a caption, lyrics and a maximum length; `lyricsNeed` estimates the length the lyrics need (~0.6 s per sung character or English word, 4 s per section tag, 15 s intro/outro) and warns with a one-click fix when the maximum is shorter.
- `web/src/components/RefImages.vue`: reference image list, each image with a subject description. Image N is `<Subject N>` / `<Picture N>`. With `video` it is the reference video list: video k is `<Video k>` and `<Subject images + k>`.
- `web/src/components/ImageDrop.vue`: drag-and-drop upload for the first / last frame.
- `web/src/components/JobCard.vue`: job card with progress, video, picture or audio player (with lyrics), reuse button, Reference / Frame buttons on pictures and an Upscale menu (upscaler × targets above the video's size) on videos; the prompt is clamped to three lines with a Show more toggle.
- `doc/directing-workflow.md`: the agent workflow for directing a production of any genre (animated series, drama, documentary, talking head, commercial, MV) through the API: first confirm aspect ratio, resolution and speech language with the user; all shots on FastH3 OmniRef, voices and narration generated by H3 from fixed voice phrases (no TTS), no captions, casting clips as references only for recurring roles, ~2-minute batches each assembled into a preview the user approves before the next batch is planned, files under `outputs/<title>/`, and a finished film with a MOSS-Image poster cover with the title a `publish.md` (title, description, hashtags), and a soft English/target-language subtitle track from faster-whisper (after `/api/unload`). Follow it when asked to make a multi-shot video.
- `doc/novel-adaptation-workflow.md`: adapting a novella or novel (`.epub` / `.txt`) into a series over many sessions: split the book into chapter files, a read-through that writes one note per chapter, a bible (`bible/cast.json` is the single source of every look, keep and voice, with age/costume variants each cast once), a season plan, and a `PROGRESS.md` resume file a new session reads first. Each episode is then made with `directing-workflow.md`. Follow it when asked to adapt a book.
- `web/src/style.css`: design tokens, with light and dark sets.
- `doc/screenshots/`: README screenshots (WebP, 1440×1000 viewport, taken with Playwright against the deployed server). Retake them when the UI changes visibly; fill the form with real content rather than leaving it empty. Light theme only. The user wants the red panda / zebra material, not the Li Bai (将进酒) jobs, in these screenshots; the overview hides reference-mode cards with a script before the shot.

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
- Data directory on the server: `$H3_DEPLOY_DIR/data/`, containing `jobs.db`, `videos/`, `pictures/`, `music/`, `thumbs/`, `uploads/`.
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
