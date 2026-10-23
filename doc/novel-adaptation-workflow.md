# Adapting a novel into a series: an agent workflow

This guide covers what is different when the source is a novella or a novel (an `.epub` or `.txt`) and the result
is a series of episodes made over many sessions: splitting the book, reading it once in full, writing down
everything the analysis found, and keeping characters and voices identical from the first episode to the last.

How a single episode is shot is not repeated here. Each episode is produced with
[directing-workflow.md](directing-workflow.md): storyboard in ~2-minute batches, one take per shot, QC, assembly
without audio processing, poster cover, `publish.md` and per-shot soft subtitles.

The agent never relies on its memory of the book or of earlier sessions. Every result of reading and planning is
saved to a file before the next step, so a new session (or a different agent) continues from the files alone.

## Step 0: confirm the settings

Ask the user in one question, recommended choices first, and record the answers in `PROGRESS.md`:

| Setting | Recommended |
|---|---|
| Aspect ratio, resolution, speech language | 16:9, 544p, the language the user names (as in directing-workflow.md) |
| Episode length | 3–5 minutes (2–3 batches); shorter episodes keep each session's work finishable |
| Scope | Faithful to the main plot, side plots cut; or a condensed season of N episodes |
| Visual treatment | From the genre table in directing-workflow.md; stylized looks hold faces best at 544p |

Use only books in the public domain or ones the user holds adaptation rights to. Dialogue from a public-domain
book may be used; otherwise rewrite it.

## Project layout

```
outputs/<title>/
  PROGRESS.md                 the resume file: settings, phase, episode table, next action, open issues
  source/
    book.epub | book.txt      the original file, untouched
    chapters/001.txt ...      one plain-text file per chapter
    chapters.json             index: number, title, character count, file
  analysis/
    chapters/001.md ...       one note per chapter, written during the read-through
    synopsis.md               the whole story after the read-through: logline, arc, ending, themes
    timeline.md               when each chapter happens; ages and costume changes over time
  bible/
    cast.json                 the single source of every look, keep and voice string (machine-read)
    characters.md             the human version: role, arc, relationships, first and last chapter, variants
    locations.json            fixed English phrase per recurring location
    style.md                  style line, score lines per arc, narrator lead-in, the no-text clause
    glossary.md               names and terms, spelled as they must appear in prompts and subtitles
    changes.md                every change to the bible, with the date, the reason and episodes affected
  plan/
    season.md                 chapters → episodes, each with its arc, cliffhanger, cast and new characters
  refs/                       one reference image per cast variant (never regenerated once used)
  casting/                    casting clips and contact sheets
  episodes/E01/ ...           one folder per episode, laid out as a directing-workflow production
  scripts/                    split_book.py, prompts.py (reads bible/), studio.py, assemble.sh, qc.sh
  series/                     the series poster, a theme song if any, the season's publish notes
```

## Step 1: split the book into chapters

Copy the book into `source/` (a downloaded file is untrusted: copy it into a new empty folder first and run the
splitter with `python3 -I`), then run the repository's splitter, standard library only:

```bash
python3 -I scripts/split_book.py outputs/<title>/source/book.epub outputs/<title>/source
```

It reads an epub in OPF spine order (XHTML stripped to text, paragraphs kept) or decodes a txt as UTF-8 or
GB18030, splits on chapter headings, drops the Project Gutenberg licence, and writes `source/chapters/NNN.txt`
and `source/chapters.json`. Headings it recognises: a Roman numeral line followed by an all-capitals title
(`V` / `INTO THE NIGHT LAND`), `Chapter N ...`, and `第N章/回/节/卷 ...`. A lone numeral line is layout debris,
not a heading: in *The Night Land* it produced empty and half chapters until the rule required the title.

Check the printed list before going on: the count, the order, no 0-word or tiny chapters, nothing of the front
or back matter. Copy the splitter into the project's `scripts/` and adjust it there if a book needs another
heading pattern. Record the chapter count and total length in `PROGRESS.md`.

## Step 2: read the whole book once

Read the chapters in order, one at a time. After each chapter, write its note before opening the next one, so
nothing depends on holding the book in context. A long novel takes several sessions: mark each chapter done in
`PROGRESS.md` as its note is saved, and when the session's context is getting full, stop after a note and leave
"Next action" pointing at the next chapter. Read chapters over ~15,000 words in parts and append to the note
after each part. Keep each note under about 400 words:

```markdown
# Chapter 12: <title>

## Events
- <what happens, in order, in a few bullets>

## Characters
- <id>: <what they do here; any change in age, look, costume, injury, status>

## Places
- <location id>: <new or recurring>

## Lines worth keeping
- <speaker>: "<a short line that defines the scene>"

## Time
<when this happens relative to the previous chapter>

## Adaptation notes
<what is visual, what is interior monologue that needs narration, what can be cut>
```

Use stable ids for characters and places from the first chapter on (`mathilde`, `loisel`, `flat`), and record
every alias a character goes by. When the read-through is done, write `analysis/synopsis.md` and
`analysis/timeline.md` from the notes, not from memory.

## Step 3: the bible

Build the bible from the chapter notes. It is the reference every later episode reads.

`bible/cast.json` holds the strings that go into prompts; nothing else may spell a look or a voice:

```json
{
  "mathilde": {
    "name": "Mathilde Loisel",
    "voice": "the soft, light, wistful soprano voice of a young woman in her twenties, ... speaking English",
    "voice_note": "二十多岁女声，轻柔偏高，带一点气声和怅惘",
    "variants": {
      "day":  {"look": "Mathilde Loisel, a slender ... day dress", "keep": "Preserve the same ...",
               "ref": "refs/mathilde_day.png", "chapters": "1-3"},
      "ball": {"look": "...", "keep": "...", "ref": "refs/mathilde_ball.png", "chapters": "4"},
      "old":  {"look": "...", "keep": "...", "voice": "the same woman's voice ten years later, ...",
               "ref": "refs/mathilde_old.png", "chapters": "8-10"}
    }
  }
}
```

Rules:

- A **variant** is a look that recurs: a different age, a costume worn across many scenes, a lasting injury.
  Each variant gets its own casting clip and reference. A costume worn in one or two shots is written into those
  shots instead, with the closest variant as reference (a reference carries its costume into the shot unless the
  prompt names the new one).
- A variant may override the voice (age, illness); otherwise the character's voice applies everywhere.
- Plan every variant from `analysis/timeline.md` before the first episode, so ages and costumes are decided once.
- Give the main voices clearly different gender, age or pitch. Minor characters who speak in one episode still
  get a voice entry, so a later appearance sounds the same.
- `locations.json` does the same for places; `style.md` fixes the style line and one score line per arc.
- `prompts.py` loads `bible/` and builds every prompt; it never contains a look or a voice of its own.

Changing the bible after an episode is made changes how a character looks or sounds in later episodes. Avoid it;
when it is unavoidable (a voice that the user says does not work), record it in `bible/changes.md` and say which
episodes were made with the old wording.

## Step 4: the season plan

Write `plan/season.md`: which chapters each episode covers, its arc in two or three sentences, the cliffhanger it
ends on, the cast variants it needs, and the characters it introduces. Use the episode length from Step 0 and the
speech budget of directing-workflow.md (about 2.5 English words or 3–3.5 Chinese characters per second): a novel
has far more words than an episode can speak, so plan narration for interior monologue and time jumps, and cut
side plots rather than rush the main one. Show the plan to the user before casting.

## Step 5: casting

Cast every variant needed by the first two or three episodes now, and later variants before the episode that
first needs them (directing-workflow.md, Step 3). Cast all variants with the same style line and framing so
they match. Once a reference has been used in a finished episode it is never regenerated; a bad reference is
replaced only before its first use.

The user listens to the casting clips to approve the voices. Record the approval in `PROGRESS.md`.

## Step 6: produce one episode at a time

For episode N:

1. Read `PROGRESS.md`, `plan/season.md` for episode N, the chapter notes it covers, `bible/` and the previous
   episode's storyboard (for continuity: where everyone was, what they wore, the last line).
2. Re-read the source chapters themselves for the scenes being written, for dialogue and detail.
3. Produce the episode in `episodes/EN/` with directing-workflow.md: storyboard in ~2-minute batches, one take per
   shot, QC, assembly, cover, `publish.md`, soft subtitles. Shot names carry the episode (`E03_S07`).
4. Update `PROGRESS.md` after every batch, not only at the end of the episode.

Consistency rules across episodes:

- Every cast member appears through their `cast.json` variant and its reference; no ad-hoc descriptions of a
  recurring character.
- Recurring places use their `locations.json` phrase; the style line and the arc's score line never change.
- Open each episode on an establishing or recap shot and end it on its planned cliffhanger.
- Add the glossary's names to the whisper `initial_prompt` for the subtitles.

## PROGRESS.md: the resume file

A new session reads this file first and does what its "Next action" says. Keep it short and current:

```markdown
# <title>: progress

## Settings
16:9 · 544p · English speech · episodes ~4 min · faithful, side plots cut · stylized 3D, painterly

## Phase
Production (read-through, bible, season plan and casting done)

## Episodes
| Ep | Chapters | Status | Length | Notes |
|---|---|---|---|---|
| E01 | 1–3 | done | 4:12 | |
| E02 | 4–5 | shooting batch 2/2 | | S05 redo queued |
| E03 | 6–8 | planned | | needs mathilde_old casting |

## Next action
Wait for E02 batch 2 (jobs in episodes/E02/scripts/jobs.json), QC, assemble E02.

## Open issues
- The user found loisel's voice too nasal in E01; not changed yet (would need bible/changes.md entry).

## Resume order
PROGRESS.md → bible/ → plan/season.md → the current episode's folder → its chapter notes and source chapters.
```

Episode status values: planned, storyboarded, shooting batch k/n, assembled, subtitled, done.

## Step 7: the series

When the season is done, assemble nothing new: each episode is its own film. Make a series poster
(`series/poster.png`, MOSS-Image, as in directing-workflow.md) and `series/publish.md` with the series title,
description, hashtags and the episode list. A theme song (MiniMax Music 3, `kind=music`) can open every episode
as guide audio on its first shot; make it once and reuse the same file.

## Known limits

- Voices are fixed by text, not cloned: the same voice phrase gives a similar voice, not an identical one. Keep
  the phrase byte-for-byte identical and let the user judge the casting clips.
- A long read-through costs time; write each chapter note before reading on, and never re-read the whole book
  in one session.
- Faces drift slightly between episodes as between shots; always pass the variant's reference, even for a
  character seen from behind.
