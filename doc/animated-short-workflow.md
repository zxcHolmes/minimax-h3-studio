# Animated short series with MiniMax-H3 Studio: an agent workflow

This is the production flow an agent (Claude Code or similar) follows to direct a multi-episode animated
short with consistent characters and voices, using only the H3 Studio HTTP API and ffmpeg. It was worked out
on a lion-themed series of roughly 110-second episodes, 8 shots each.

The agent plays director, writer, casting, editor and QC. The user approves the concept and does the final
review, especially listening to the dialogue, which the agent cannot hear.

## Setup

| Item | Choice |
|---|---|
| Resolution | 544p, 16:9 (960×544) |
| Text shots (establishing shots, character tests) | `mode t2v`, LoRA `larryvrh-v4` (fl2va base + `minimax_h3_turbo_v4_step600_ema`) |
| Shots with characters | `mode r2v`, model `fasth3-omniref` (FastH3 OmniRef 8-step, the only reference model) |
| Shot length | 5–15 s, one continuous shot per job |
| Throughput (RTX 4090) | 5 s ≈ 40 s; 15 s t2v ≈ 140 s; 10 s r2v ≈ 90 s |

Why these choices:

- larryvrh loses identity in reference mode, so it is only used for text shots. Reference shots use FastH3
  OmniRef; the lightx2v ref LoRAs it replaced smeared fast motion into streaks.
- Stay at 544p. 768p is about 2× slower, and a 15 s
  768p job once failed at the very end with NaN audio (`avcodec_send_frame() returned 22`).
- The server runs one job at a time in FIFO order, so submit a whole episode at once and let it queue.

## Project layout

Keep everything for a series under one folder (for example `outputs/<series>/`, which is git-ignored):

```
00_project.md            premise, specs, style line, folder map
01_characters_voices.md  character bible: fixed look + fixed voice per character
02_ep01_storyboard.md    one section per shot
03_ep01_log.md           job ids, seeds, timings, QC verdict per shot
prompts/                 the exact text submitted for every job
refs/                    one cropped reference image per character
refs/candidates/         contact sheets used to pick the reference frames
clips/                   downloaded shots; clips/casting/ holds the character tests
qc/                      contact sheets of every shot
scripts/                 API client, prompt builders, jobs.json
ep01.mp4                 the finished episode
```

Write prompts to files and build them with a script instead of typing them per job. The script is the
single source for every character's wording, which is what keeps characters and voices stable.

## Step 1: concept and character bible

1. Write the premise and episode arc. Use original characters; do not reuse protected characters, names or
   lines from existing films.
2. For each character, fix three strings and never paraphrase them later:
   - **look**: one English noun phrase with species, age, colours and two or three distinctive marks
     (for example a head tuft, a notched ear, a broken tusk). Distinct marks are what the model holds on to.
   - **keep**: one sentence for the ref2va `retention_analysis` line ("Preserve the same ...").
   - **voice**: one English phrase for timbre, age and pace, for example
     `the bright, clear, high-pitched voice of an eight-year-old boy, quick and eager`.
     Write a short Chinese (or target-language) description next to it for the human reader.
3. Fix one style line and append it to every prompt:

   > Stylized 3D animated feature film look, high-end family animation, expressive animal acting with realistic
   > animal anatomy, soft global illumination, warm golden African savanna light, rich saturated colors,
   > detailed fur. No text, no subtitles, no captions, no logos, no watermarks.

   The "no text, no subtitles" clause matters when the episode must have no burned-in captions.
4. Name recurring locations the same way too (one fixed English phrase per location).

## Step 2: casting (character tests)

For each character, submit a 5 s t2v job: the character alone, centred, fully visible, three-quarter view,
plain softly lit background, a slow push-in, and one line of dialogue in the target language. This gives
both the reference image and a voice test the user can listen to before the episode is made.

```
integrated_multimodal_description: [Shot 1] <style line> Character introduction shot on an open patch of
short golden grass ... Centered in frame and fully visible, <look> stands facing the camera in a
three-quarter view. ... says in <voice>: <d>[Chinese] 我叫阿炎，我将来要当草原之王！</d> Static medium-wide
shot, slow gentle push-in.

overall_soundscape: ..., the cub's bright excited boy's voice speaking Mandarin Chinese.

non_diegetic_music: Soft warm African percussion and low strings, gentle and quiet.
```

Then pick the reference frame:

```bash
# five evenly spaced frames side by side, to choose from
ffmpeg -i clips/casting/ref_ayan.mp4 -vf "select='eq(n\,6)+eq(n\,36)+eq(n\,66)+eq(n\,96)+eq(n\,120)',scale=384:-1,tile=5x1" \
  -frames:v 1 refs/candidates/ayan_sheet.jpg
# the chosen frame, cropped tightly around the character (crop=w:h:x:y in 960x544 pixels)
ffmpeg -i clips/casting/ref_ayan.mp4 -vf "select='eq(n\,6)',crop=420:504:230:40" -frames:v 1 refs/ayan.png
```

Choose a frame with the mouth closed or a neutral expression, the whole body visible and the distinctive
marks readable. Crop tightly: the character should fill the reference image.

## Step 3: storyboard

Plan about 8 shots per episode (6 × 15 s + 2 × 10 s ≈ 110 s). For each shot write: length, mode, cast
(which references), the action, every line of dialogue with its speaker, sound effects and music.

Rules that worked:

- One job is one continuous shot. Do not ask for cuts inside a job.
- At most 3 characters (references) per shot, at most 3–4 spoken lines per 15 s.
- Characters without a speaking or visual role in a shot are left out of its cast.
- An establishing shot without characters is a t2v shot; a new location can be introduced that way.
- End episodes on a hook (the villain watching, a threat) to carry into the next one.
- New characters introduced in a later episode get their own casting job first. Shots that do not need them
  can be submitted right away while their casting job runs.

## Step 4: prompts

Dialogue syntax: `<d>[Chinese] 台词</d>`, introduced by `says in <voice>:` so each line carries its speaker's
fixed voice. In `overall_soundscape`, say which voices are heard and that they speak Mandarin Chinese.

**Text shots** use the t2v layout:

```
integrated_multimodal_description: [Shot 1] <style line> <scene and camera move>

overall_soundscape: <ambience, effects, voices>

non_diegetic_music: <score>
```

**Reference shots** use the official ref2va layout. `<Subject N>` and `<Picture N>` follow the order the
`ref_image` files are sent:

```
subject_definitions:
<Subject 1> is <look of character 1>, as shown in <Picture 1>.
<Subject 2> is <look of character 2>, as shown in <Picture 2>.

summary:
[reference generation] In one continuous 15.0833-second shot, <one-sentence summary using the subject tags>

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - <keep sentence>
<Subject 2> (appears in [Shot 1]): fully_preserved - <keep sentence>

detailed_description:
Visual style: <style line> <optional scene lighting, e.g. night, drought, dark canyon>

[Shot 1, 00:00.000-00:04.000] <action>

[Shot 1, 00:04.000-00:09.000] <Subject 1> looks down at his son and says in <voice>: <d>[Chinese] ...</d>

[Shot 1, 00:09.000-00:15.083] ...

overall_soundscape:
<ambience, effects, which voices speak Mandarin Chinese>

non_diegetic_music:
<score>
```

The real length is the frame count snapped to the 17k+5 grid at 24 fps: 15 s → 362 frames (15.0833 s),
10 s → 243 frames (10.125 s), 5 s → 124 frames. Use that length in `summary` and clamp the last beat to it:

```python
def frames(seconds):
    n = max(5, round(seconds * 24))
    return n + (5 - n % 17) % 17
```

## Step 5: submit through the Studio API

`POST /api/jobs` takes a multipart form. One job per shot:

```bash
curl -s -X POST http://<host>:8190/api/jobs \
  -F "prompt=<prompts/ep01_S04.txt" -F resolution=544p -F lora=fasth3-omniref \
  -F aspect_ratio=16:9 -F duration=15 \
  -F ref_image=@refs/leizong.png -F ref_image=@refs/ayan.png
```

- `prompt=<file` makes curl read the field from the file (keeps newlines and Chinese text intact).
- Leave `seed` out for a random one; the response returns it. Record id, seed, prompt file, LoRA and refs for
  every job (a `jobs.json` keyed by shot name works well), so any shot can be redone or reproduced.
- `GET /api/jobs/{id}` until `status` is `done` or `failed`, then download `video_url`. Poll every 15 s.
  Run the wait loop in the background and let the harness notify you instead of sleeping in the foreground.
- `GET /api/presets` lists valid resolutions and LoRA ids.

## Step 6: QC and redo

For every shot, make a contact sheet (one frame every 2 s) and check it against the storyboard:

```bash
ffmpeg -i clips/ep01_S04.mp4 -vf "fps=1/2,scale=320:-1,tile=8x1" -frames:v 1 qc/ep01_S04.jpg
ffmpeg -i clips/ep01_S04.mp4 -af volumedetect -vn -f null - 2>&1 | grep -E "mean_volume|max_volume"
```

Check: duration, the cast looks like the references (marks, colours), the action follows the beats, no
burned-in text or broken anatomy, and the audio track is present. Note smaller drifts in the log instead of
redoing (for example a mane getting lighter late in a shot).

Redo a shot by resubmitting the same prompt (new random seed), or adjust its beats if the model keeps missing
an action. Record the new job under the same shot name.

The agent cannot judge pronunciation or timbre. Say so in the report and ask the user to listen.

## Step 7: assemble the episode

Shots come out at very different loudness (about −35 to −15 dB mean). Normalise each shot, reset timestamps
so the result is constant 24 fps, pad or trim each audio track to its video length, and add tiny fades to
avoid clicks at the cuts:

```bash
ins=""; fc=""
for i in 1 2 3 4 5 6 7 8; do
  f=clips/ep01_S0$i.mp4; ins="$ins -i $f"
  d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $f)
  fc="$fc[$((i-1)):v]setpts=N/24/TB,setsar=1[v$i];"
  fc="$fc[$((i-1)):a]asetpts=PTS-STARTPTS,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,"
  fc="${fc}apad=whole_dur=$d,atrim=0:$d,afade=t=in:d=0.05,afade=t=out:st=$(python3 -c "print($d-0.08)"):d=0.08[a$i];"
done
fc="$fc$(for i in 1 2 3 4 5 6 7 8; do printf "[v$i][a$i]"; done)concat=n=8:v=1:a=1[v][a]"
ffmpeg -y $ins -filter_complex "$fc" -map "[v]" -map "[a]" -fps_mode cfr -r 24 \
  -c:v libx264 -crf 16 -preset slow -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart ep01.mp4
```

Verify with `ffprobe -count_frames`: the frame count equals the sum of the shots, `avg_frame_rate` is
exactly 24/1, and the audio and video durations match. Without `setpts=N/24/TB` and `-fps_mode cfr` the
concat output had a variable frame rate and drifted 0.75 s longer than its frames.

## Step 8: report

Give the user the episode path, its length, any shots that were redone, and a short list of things to check
by eye and ear (drifts noted during QC, any storyboard action that came out weak, voices and pronunciation).
Keep the log file updated so the next episode, or a redo, starts from recorded facts.

## Next episodes

Reuse the bible, the references and the prompt builder; write a new storyboard and a new prompt script that
imports the shared character definitions. Add new characters to the bible and cast them first. Keep the same
seeds policy, QC and assembly so episodes match in loudness, frame rate and look.

## Known limits

- Realistic close-up faces are soft at 544p; stylized animation hides this well.
- Characters can drift slightly within a long shot (colour of a mane, face proportions).
- Characters cast in different jobs can come out in slightly different styles (one more realistic than
  another); generate all casting jobs with the same style line and similar framing to limit this.
- Specific physical actions (a leap from a height, catching something in the mouth) are not always followed.
