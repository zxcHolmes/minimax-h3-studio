# Science Fables: upscale before final composition

This is the finishing preset for future Science Fables shorts. Generate and approve the story footage
first, super-resolve the accepted footage, normalize the delivery canvas, and only then compose final
captions and graphic text. Final portrait delivery is **1080 x 1920, square pixels, native 24 fps**.
This requirement does not retroactively change delivered films or replace scheduled YouTube uploads.

## Required model and processing order

Use Studio's **RelayVSR 2x** choice:

- Model: `relayvsr_x2_lightx2v_int8_convrot.safetensors`.
- Matching decoder: `relayvsr_flash_vae_x2_fp32.safetensors`.
- API choice: `upscaler=relayvsr`, `target=2x`.
- Keep source audio, frame count and frame rate. Do not interpolate 24 fps to 30/60 fps.

The required order is:

1. Generate the H3 segments, select the accepted takes and review their actual narration and continuity.
2. Run RelayVSR 2x on each accepted **5-15 second segment before burning captions**. Reuse an existing
   completed upscale of that exact take rather than submitting it twice. Store source job ID, upscale
   job ID, model filenames, seed and paths in the film's production ledger.
3. Normalize the upscaled picture to 1080 x 1920 with a high-quality downsample. Review any crop.
4. Assemble the opening and story segments, preserve the reviewed edit timing and mix narration/music.
5. Render captions and any new title/graphic overlays at the final 1080 x 1920 resolution. Recalculate
   font sizes, outlines and safe zones for this canvas rather than stretching a 768-pixel subtitle layer.
6. Check the full film, final frame count, subtitle timing, sound, text and technical metadata before release.

Per-segment processing also bounds memory use: the deployed pipeline decodes source and output frames
into RAM. Do not send the assembled approximately 90-second film through this in-memory path as the
default finishing step.

Keep accepted local reframes and corrections. If an accepted file contains a local reframe that is not
present in the Studio source job, preserve that correction in the upscaled edit with appropriately scaled
crop coordinates; do not silently substitute the uncorrected original job. Never super-resolve a film
with burned captions when clean accepted segments are available.

For an opening with an already embedded title, check every letter after upscaling. Prefer compositing
crisp title artwork after canvas normalization when possible. Keep the original high-resolution static
`cover.png` for the separate YouTube thumbnail upload.

## Actual size controls on the deployed GPU machine

Checked directly over SSH on **2026-11-06**:

- Deployed Studio in `$H3_DEPLOY_DIR`; ComfyUI in `$H3_COMFYUI`.
- Both required 2x checkpoint/decoder files are installed.
- Live `/api/presets` exposes RelayVSR targets `2x` and `4x` only.
- The deployed `RelayVSRConditioning` and `VSRDecode` nodes have no width/height or scale-ratio input.
  The checkpoint/decoder pair determines the native output factor. `detail` changes added detail,
  not output dimensions.
- `POST /api/jobs/{source_job_id}/upscale` validates the factor, and the server rejects output short
  sides above 2176 pixels. A `target=1080p` request is not a supported RelayVSR request here.

| Stage | Dimensions for the current portrait source |
| --- | --- |
| H3 source | 768 x 1344 (4:7, close to 9:16) |
| Native RelayVSR 2x intermediate | 1536 x 2688 |
| Exact 9:16 center crop | 1512 x 2688 (12 pixels removed from each side) |
| Final downsample and composition canvas | 1080 x 1920 |

**The final export size is customizable through postprocessing; native inference still runs at 2x.**
Do not describe a smaller export as reduced GPU inference work. Do not shrink the low-resolution input
first merely to make the 2x output equal 1080 pixels: that discards source detail before enhancement.

If the small center crop would remove important action, use a reviewed reframe or an aspect-preserving
fit/pad instead. Do not stretch 4:7 footage into 9:16. A fit of this example is 1080 x 1890 with 15 pixels
of padding above and below; choose a suitable background rather than assuming black bars are desirable.

The upstream [LightX2V runner](https://github.com/ModelTC/LightX2V/blob/main/scripts/relayvsr/README.md)
also documents fractional output ratios by resizing after native inference. That is a different execution
path and is not a custom-size option exposed by this deployed Studio API.

## Requests and local finishing example

Submit an upscale of an accepted Studio source job, then poll that returned job and download its
`video_url`. Record the ID immediately; after an ambiguous POST result inspect existing jobs before retrying.

```bash
curl -fsS -X POST "$STUDIO_URL/api/jobs/$SOURCE_JOB_ID/upscale" \
  -F upscaler=relayvsr -F target=2x
```

For an existing **1536 x 2688** intermediate, the exact crop/downsample is:

```bash
ffmpeg -i accepted.SR-2x.mp4 \
  -map 0:v:0 -map '0:a?' \
  -vf 'crop=1512:2688:12:0,scale=1080:1920:flags=lanczos,setsar=1' \
  -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
  -c:a copy -movflags +faststart accepted.1080p.clean.mp4
```

This command produces clean normalized picture, not the captioned final film. Adapt the crop for other
source dimensions. Preserve the accepted frame-based trims and reviewed ASR timing when assembling;
upscaling and spatial resizing alone must not shift the speech/caption timeline. Render the English
word captions at 1080 x 1920 after the resize. Export the publication copy as MP4/H.264 with compatible
AAC audio, then inspect the beginning, ending, joins and text before publishing.

Keep native source, 2x intermediate and final delivery as separate files. Record the final file's actual
width, height, duration and model provenance in its gallery metadata and publishing manifest.
