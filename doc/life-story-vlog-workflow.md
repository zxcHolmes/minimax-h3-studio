# Life-story vlog: a famous person's whole life, told to a selfie camera

This guide covers one format: a historical figure vlogs their own life at every age, as if they had owned a
smartphone. Other people interrupt, steal the camera and have the last word. Follow
[`directing-workflow.md`](directing-workflow.md) for the general procedure (project folder, speech budget, API usage,
assembly, subtitles). This guide states what differs. It comes from *Einstein's Vlog* (2026-11).

## 1. The format in one paragraph

A modern vlog dropped into every era is the joke and the hook. It only holds for several minutes if the film moves
through **events**, with **other people** and **changing pictures**. A person talking to the lens in one room per age
is a slideshow. The first cut of *Einstein's Vlog* made that mistake: every clip was one person in one place, with no
group photos, prizes or discoveries on screen.

## 2. Confirm first

Person, spoken language, subtitle languages, frame (portrait suits the format), resolution (768p default) and rough
length. Use one spoken language throughout and let the accent carry the origin.

## 3. Research anecdotes before writing anything

Collect real moments, not a timeline of achievements. Good material has a person to play against and a turn at the end:

| Einstein example | Why it works |
| --- | --- |
| Threw a chair at his violin teacher; his little sister tells on him | Child comedy, a second voice |
| Ate birthday caviar without noticing, still lecturing | Character through action |
| "I have completely solved the problem", said to a baffled Besso under a clock tower | The discovery as a scene |
| Chaplin: "They cheer me because everyone understands me..." | A famous co-star steals the shot |
| The ambassador collects the Nobel for an absent winner | The protagonist's absence is the joke |
| The night nurse: his last words were in German, and she spoke none | Someone else ends the story |

Write a fact sheet in `00_project.md`. Separate three kinds of line: documented, reported or anecdotal, and invented for
the film. Invented lines must fit the character, must not put false claims about real events or real people's beliefs
in their mouths, and are disclosed in `publish.md`. Check dates against the person's age before writing labels.

## 4. Structure

- **Order by event, and label by age.** Plan one to three scenes per life period. Spend scenes on turning points and
  skip quiet years. The age tag does the bookkeeping.
- **Hook in the first line.** Start with a contradiction, such as "I'm five. People think I'm slow."
- **Set up a motif and pay it off.** A prop or a line from the first scene returns at the end. The compass needle
  returns on an empty desk, with the child's line in voiceover.
- **Alternate tone.** Comedy earns the serious passages. Let one or two gravest moments stay solo and slow on purpose;
  they hit harder after a crowded film.
- **Do not tell what you show.** If a scene shows an event, the next vlog entry should react to it, not retell it.
- **End on someone else.** A witness picking up the camera after the person has gone is the format's natural ending.

Length: *Einstein's Vlog* came to about 7 minutes with 34 clips of 5–15 s. Prefer scenes of 8–12 s, and cut a retelling
before cutting a scene.

## 5. Shot types and which model to use

Choose per shot. **The default is a Qwen-composed first frame + `larryvrh-v4-sparse`** (the directing workflow's fast
mode): it is much faster than reference mode (5 s at 768p: about 38 s against about 67 s) and it gives direct control
over who is in frame and where.

| Type | What it is | Route |
| --- | --- | --- |
| Solo selfie | Direct address; use sparingly | First frame + 4-step LoRA |
| Group selfie | The person and others in one frame, trading lines | First frame + 4-step LoRA |
| Stolen camera | Someone else films and talks about the person | First frame + 4-step LoRA |
| Witness view | The person is absent or far away (ceremony, White House, night nurse) | First frame or text-to-video + 4-step LoRA |
| Cutaway | What the person is talking about; picture only (see section 8) | Text-to-video + 4-step LoRA, 5 s |
| Hard reference shot | Only when a first frame cannot hold the identity through the action | `fasth3-omniref` |

Within a clip, give the camera something to do: a swing to the other speaker, a tilt up to a landmark or down to the
feet, walking, a flash going off. Never write blanket rules such as "only one person in the frame"; they flatten the
whole film.

## 6. Age cards and first frames

- **Cards.** One plain-backdrop reference per life stage (about 12 for a long life), written as `the young <name> at 22`
  plus face, hair and period costume. Generate two candidates per card with `qwen-image-21-turbo` and freeze one. Nearby
  ages can share a card.
- **Check apparent age.** Text-to-image tends to make young adults look ten years older. Fix them with a Qwen edit
  ("the same man, clearly younger: smooth skin, no forehead lines") rather than regenerating from scratch.
- **Famous older faces come out strongest.** Pick the age that looks most iconic for the cover.
- **First frames.** A Qwen edit with the age card first (it sets the 9:16 canvas), then the location card if there is
  one, with everyone else described in the prompt. One-scene supporting characters need no card. Without any reference,
  use text-to-image with `aspect_ratio=9:16`. Two candidates per shot, inspected on a contact sheet.
- **Cover.** Three ages of the same person squeezed into one selfie is a strong poster: pass three age cards to a Qwen
  edit, with the title in quotes. Animate it for 4 s with first-frame mode and a shutter click.

## 7. Prompt rules learned the hard way

- **Never write "phone view" or "smartphone screen" in an image prompt.** Qwen draws the phone and its bezel inside the
  frame. Write "selfie taken by X" or "a candid vertical photograph, full frame, with no device, screen or border".
- **Name who holds the camera, and check it.** Qwen often gives the camera arm to the main character regardless. If the
  chosen frame differs from the script, rewrite the shot to match the frame rather than regenerating the image.
- **Rewrite the action to fit the actual frame.** The video prompt must start from what `<Picture 1>` shows: who is
  beside whom, and who holds which prop.
- **Give each speaker their own stable voice string and speaker ID in every line**, with an accent suited to the
  character. Say that lips move only on a speaker's own line, and that the last line ends before the shot does.
- **Keep to the speech budget.** Up to about 2.3 words per second, less for the very old or for children, and less
  again when there is business with props. The first cut filled almost every clip to the last frame, which leaves no
  held looks and nothing to trim. Aim to end the speech 1–2 s before the clip's end.
- **Ban text in frames.** Require "no readable writing" on every letter, telegram, newspaper, notebook and clock face.
- **Give no music in the clips:** `non_diegetic_music: N/A`, and specify rich ambience in `overall_soundscape`.

## 8. Cutaways: show what the person is talking about

Replace the picture for a few seconds and keep the clip's audio, so the voice continues over what it describes. This is
the cheapest way to break up a single-scene clip, and already generated clips need no regeneration.

- Generate 5 s text-to-video shots with `larryvrh-v4-sparse` and `aspect_ratio=9:16`, with no recognizable faces.
- Pick moments an audience cannot picture unaided: the thought experiment, the discovery visualized (curved spacetime,
  a chain reaction), the event happening elsewhere (an eclipse, printing presses), a consequence (ruins, a ransacked room).
- Inspect them for orientation. Text-to-video occasionally renders portrait content sideways (one in ten here). Fix it
  locally with `transpose` plus a 9:16 crop rather than regenerating.
- Time each one from the clip's word timing: start at the first word it illustrates, end at the last, and keep it inside
  the clip. Overlay it in the edit and drop its own audio.
- About one cutaway for every two or three talking clips is a sensible density; leave emotional peaks on the face.

## 9. Music and sound

Use one or two Music 3 instrumental beds (solo instrument + piano suits a biography), ducked under speech with
`sidechaincompress` at about 0.20 gain. Use section-tagged instrumental lyrics and `--form-string`, as usual. Music 3
may deliver much less than requested (219 s from 240 s, 167 s from 200 s, 68 s from 100 s), so check the mp3 length
before mixing and plan to reuse a passage or leave gaps on loud scenes. For a long film,
use two beds matching the arc, for example a playful one and then a grave-to-tender one starting at the film's dark turn.
Leave the very last scenes silent if the ending can bear it.

## 10. Edit and subtitles

- Mixed routes need no extra handling; every clip is 768×1344 at 24 fps. Add new clips between existing ones rather than
  regenerating. Keep earlier cuts: new versions get new file names.
- **Age tags:** a small "Age 22 · Zurich, 1901" label for the first 3 s of each life stage, burned in by the edit. It is
  the one permitted burned-in text apart from the cover. Skip it when a scene continues the previous stage.
- **Transcribe each clip,** shift the word timing into the edit, and review **raw ASR text**, not text already merged
  with the script. Comparing a merged version hides real differences.
- **Expect these ASR errors:** place and proper names (Bern → "Burn", Szilard → "Zillard"), spelled-out years, foreign
  words ("oh, weh" → "oh, way") and accents ("Patent" → "Payton"). Correct them in a table in the edit script, and keep
  genuine differences from the script as spoken. Toddlers' lines may be missed almost entirely: check the clip's loudness
  before deciding the line was never spoken.
- **Model gibberish and stray repeats:** a non-word passage in the transcript, with real loudness in the clip, means the
  model spoke nonsense. Remove it with a jump cut, and shift the clip's word timing, rather than regenerating. Keep
  repeats that still read naturally.
- **Translate** the reviewed text yourself and mux two soft tracks. Fastest local x264 preset unless asked otherwise.

## 11. Sensitive material

- Atrocities and deaths are shown through absence and aftermath: no bodies, no gore, no symbols, flags or uniforms. Write
  these exclusions into the prompt.
- Do not put words of support for an atrocity in anyone's mouth. Do not stage a real politician's hateful speech.
- Keep the portrayal of real people fair and plausibly in character, and avoid inventing scandals. The figures should be
  historical; do not use this format for living private people or to fake statements from living public figures.
- `publish.md` states that picture, voice and music are AI-generated and that some dialogue is invented.

## 12. Checklist before submitting video

- [ ] Each life period has at least one event on screen, not only a retelling.
- [ ] Most clips have a second person, a camera move or a cutaway.
- [ ] At least a third of the speech belongs to people other than the protagonist.
- [ ] Solo clips are a deliberate choice.
- [ ] The hook, the motif and its payoff are written down.
- [ ] Every first frame is inspected: no phone bezel, right cast, right prop owner, no text.
- [ ] Every clip's speech fits the budget, with a margin at the end.
- [ ] Every real anecdote is on the fact sheet; invented lines are marked.
