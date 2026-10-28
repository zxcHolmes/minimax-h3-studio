# Adapting a novel one chapter at a time

This guide covers novels and novellas supplied as EPUB, TXT or existing chapter files. **One source chapter
becomes one independent video.** Inspect existing chapter divisions and production progress first, resume
from the earliest unfinished chapter, adapt that chapter, then follow
[directing-workflow.md](directing-workflow.md) for its complete production.

There is no requirement to finish reading the novel, prepare a season plan or study a fixed number of future
chapters before making a video. Read previous or later passages when they help resolve identity, causality,
a reference or a continuity question. Record what was read and distinguish confirmed facts from assumptions.
Do not invent a future reveal from an assumption or spoil it in the current chapter's narration.

## 1. Inspect the book and existing work before doing anything new

On every new or resumed adaptation:

1. Locate the existing `outputs/<novel-title>/` folder. Read `PROGRESS.md`, the chapter index, reference
   manifest and current production records if present. Reuse the existing project rather than starting over.
2. Check whether the source already has reliable chapter divisions: chapter files, an index, EPUB structure
   or headings in a TXT. Inspect chapter counts, order and several boundaries; do not split it again blindly.
3. Inventory chapter folders and their outputs. Reconcile final videos, subtitle tracks, storyboards, logs
   and job IDs with the progress table. Query stored API job IDs if an earlier session left jobs in flight.
4. Identify which chapters are done, partially produced or untouched. A raw clip or an assembly awaiting
   subtitles is not a completed chapter. Preserve accepted shots, references and completed work.
5. Select the **earliest unfinished source chapter** in book order. Resume its actual next stage; do not
   restart its video jobs or skip it just because a later chapter has a completed video.

If all chapters are complete, report that state. If an output is missing or unreadable, record the discrepancy
and recover from existing local files or API results where possible. Do not silently label missing work done.
When a final film exists but its record is absent, inspect it and reconstruct the record before generating
anything again. A finished chapter has a usable final video, reviewed source/translation subtitle tracks and
recorded delivery/QC; missing cover or publishing notes can be completed without regenerating the film.

Respect the scope requested by the user: a request to continue starts at the earliest unfinished chapter;
a request for several chapters processes them in source order. Do not automatically remake completed chapters.

## 2. Confirm only the missing production requirements

Use the directing guide's brief confirmation before generation. Reuse recorded answers and confirm material
changes rather than asking the same questions every chapter:

| Setting | Rule |
| --- | --- |
| Orientation | Confirm landscape or portrait and the chosen aspect ratio |
| Resolution and mode | 768p by default, reference to video with FastH3 OmniRef |
| Dialogue/narration | Confirm spoken language, whether narration is wanted and the fixed voices |
| Treatment | Confirm anime/2D, stylized 3D or realism; recommend a specific style for the story |
| Subtitles | Confirm translation language and default track; deliver original plus translation as soft tracks |
| Adaptation scope | One independent film per chapter; retain essential plot and compress redundancy |

There is no fixed episode count or required 3–5 minute runtime. Choose a chapter's film length after adapting
its actual content and budgeting speech and action. Do not merge chapters to fill a slot or divide one into
several separate releases by default. Its internal 5–15 s video segments are assembled into one chapter film.

## 3. Preserve or prepare chapter files

Use the existing reliable chapter files/index. If the book is not yet divided, preserve the original under
`source/` and run the repository's standard-library splitter with conda base:

```bash
/Users/zxc/miniconda3/bin/python -I scripts/split_book.py 'outputs/<novel-title>/source/book.epub' 'outputs/<novel-title>/source'
```

The splitter handles EPUB spine text and TXT decoded as UTF-8/GB18030. It recognizes several chapter-heading
forms, but its output still needs inspection. Check headings, body text, numbering, ordering, empty/tiny
chapters and accidental front/back matter. If the input has no supported headings, do not accept an empty
or arbitrary split as a chapter index. Adjust a project-local copy of the splitter or prepare an explicit
index from verified boundaries. Do not overwrite existing chapter files or renumber completed productions
without recording the mapping. Keep stable chapter IDs even if a heading is later corrected.

## 4. Store a searchable, shared library under the novel folder

All character and location images for the novel live under **`outputs/<novel-title>/`**, shared across its
chapters. Do not keep the only usable reference inside an unrelated production or a temporary download folder.
The chapter's job manifest records the exact shared image version it used.

```text
outputs/<novel-title>/
  PROGRESS.md                    settings, chapter status, active work and next action
  source/
    book.epub | book.txt         untouched original, when available
    chapters.json               ordered source chapter index
    chapters/001.txt ...
  analysis/chapters/001.md ...   notes for chapters actually read; no full-book prerequisite
  bible/
    cast.json                   stable identities, voice strings and versioned looks
    locations.json              set geometry, state variants and reference IDs
    style.md                    visual grammar, palette, sound and no-text rules
    glossary.md                 names, aliases and terminology for prompts/subtitles
    changes.md                  intentional changes and affected chapter range
  refs/
    manifest.json               searchable metadata for every selected asset/version
    characters/<id>/<variant>.png
    locations/<id>/<variant>.png
    candidates/                 unselected alternatives, clearly distinguished
    prompts/                    exact image generation/edit requests
  chapters/C001/ ...             one complete directing-workflow production per source chapter
    00_project.md               chapter premise, adapted plot, setting and runtime
    01_bible.md                 selected shared reference/voice IDs and chapter-specific details
    02_storyboard.md
    04_generation_log.md
    prompts/ clips/ qc/ scripts/ subs/
    jobs.json
    <chapter-title>.clean.mp4
    <chapter-title>.mp4          final independent chapter film with two subtitle streams
    cover.png
    publish.md
  series/                       optional novel-wide poster, synopsis and video index
```

Existing projects may use `episodes/E01/` or another layout. Preserve working paths, record their chapter
mapping in `PROGRESS.md` and resume in place rather than moving files for cosmetic consistency.

### Which characters need reference cards?

Create independent reference images for **principal characters and recurring characters**. A minor character
who appears repeatedly also needs a stable reference. One-off supporting roles, passersby and background
crowds do not need independent character cards; describe them directly in that segment's prompt.
If a previously incidental character recurs, register a canonical identity/reference before further use,
matching an accepted earlier appearance where available. Do not make a reference card for every person named.

### Reuse, growth and costume changes

Before generating any reference, search `refs/manifest.json`, the bible and the actual image files for a
matching character, life stage, outfit or location state. Inspect the selected images rather than relying
only on filenames. Reuse a suitable existing version across chapters.

For a character who requires a card, **growth, aging or a change of clothes/accessories requires a new
reference version before video generation**, even when the new outfit appears in only one scene. Derive
it from the canonical image with the current image-editing models where possible, preserving identity.
Examples: `child_travel`, `adult_travel`, `adult_court_uniform`, `adult_court_uniform_injured`.
A voice can evolve with age or injury; record a deliberate voice variant instead of changing wording ad hoc.
One-off extras remain covered by the prompt-only exception above.

Do not overwrite an image used by a completed chapter. Store a new version, its reason and applicable
chapter/scene range. Maintain stable character identity separately from temporary appearance. Check face,
proportions, distinctive marks, clothing and accessories on every derived version.

### Locations are reusable assets too

Generate and freeze the necessary location images before making the corresponding video segments. Empty
sets should establish layout, landmarks, materials and lighting without unrelated people. Reuse the same
location version across chapters when appropriate. Derive and register new views, day/night states, weather
or changed interiors when needed; verify spatial compatibility rather than independently reinventing a set.

For each selected asset, the manifest must record at least:

- Stable asset ID and type (`character` or `location`), name and searchable aliases.
- Version, traits/state, canonical parent if derived, and chapter/scene applicability.
- Relative local image path, image model, exact prompt path, job ID and seed.
- Selection/QC status and the features that must remain consistent.

Keep prompt wording in the shared bible; builders read it and the manifest. Each video request still maps
its ordered image uploads to local `<Picture N>` labels. Preserve these mappings in the chapter's `jobs.json`.

## 5. Read and adapt the current chapter before storyboarding

Read the current chapter in full. For a long chapter, read in parts and append notes as you go. Consult
nearby chapters or existing notes only as needed; there is no mandatory full-book skim or one-chapter lookahead.
Review prior finished chapters' summaries and endings when needed to preserve established screen continuity.
Write the current chapter's notes before moving to production:

1. What happens, in order, and which events cause the next ones.
2. Characters, motives, relationships and appearance/state changes.
3. Locations, time, important props and continuity from earlier chapter films.
4. Essential dialogue, useful narration and internal thoughts that need a visual treatment.
5. Unknowns resolved through extra reading, with the source chapter/passage recorded.

Then write the **adapted chapter script** into its `00_project.md` and `01_bible.md` before drawing up shots:

- Preserve the chapter's core conflict, decisive actions, character choices and consequential information.
- Compress repetitive descriptions, redundant dialogue, unimportant travel and side incidents that add no
  necessary information. Log important omissions so a later chapter does not assume the audience saw them.
- Convert useful prose into visible actions, expressions, props and environment. Use concise narration for
  essential context or inner thought that cannot be shown naturally.
- Write exact dialogue and narration with fixed speaker/voice IDs, emotional intent and language.
- Give this independent chapter film an engaging opening and an intelligible development and closing beat.
  A brief orientation may help returning viewers; do not force a recap, artificial cliffhanger or invented
  resolution that contradicts the chapter. Keep any genuine unresolved ending intact.
- Estimate runtime from what can actually be spoken and shown. Compress the adaptation, not the actors'
  speaking speed, when the first draft is overloaded.

Extend shared character/location records as the current chapter reveals facts. Do not invent a full future
biography just to fill a schema. Once the adapted script is written, create the storyboard and produce any
missing reference images needed by it.

## 6. Produce this chapter with the directing workflow

Use [directing-workflow.md](directing-workflow.md) as the authoritative production procedure and embedded H3
prompt reference. Shared novel references replace duplicate local reference generation, but each chapter
must select and verify its required versions explicitly.

For the current chapter:

1. Complete the adapted story, character/voice/dialogue/narration/location settings and reference selections.
2. Design the complete storyboard: 5–15 s segments, realistic speech/action budgets, cinematic detail,
   opening/closing states and natural transitions. Use names such as `C003_S007` in records and filenames.
3. Generate and freeze missing character variants and location references with current Studio picture models.
   One-off supporting characters and extras remain descriptions in the video prompt.
4. Build H3 six-section reference-mode prompts from the bible and storyboard. Use fixed voice descriptions
   for H3 dialogue/narration and exact ordered reference mappings. Submit independent ready jobs together to
   the Studio queue; wait for actual dependencies before submitting jobs that require their results.
5. QC the segments and neighboring joins, resume existing takes where possible and replace material failures.
6. Assemble the **entire chapter** into one film. Check frame count, resolution, rhythm and audio/video sync.
7. Submit that final edit to the **Qwen3-ASR transcription API** with aligned timestamps. Review recognized
   words against context, script and actual speech evidence; use the glossary to fix recognition errors,
   not to insert dialogue that was never spoken.
8. Translate the reviewed transcript yourself into the requested language. Embed source and translation as
   two selectable soft subtitle tracks, with no burned-in captions. Verify sync, language tags and switching.
9. Finish the cover, publishing notes and SRT files, record QC/delivery paths, then mark the chapter done.

No mandatory two-minute approval gates, casting-video requirement, Whisper environment or full-season plan
applies. Honor review checkpoints requested by the user. Keep the user informed during production.

## 7. Record progress so continuing is unambiguous

Update `PROGRESS.md` after meaningful stages, submitted jobs, fixes and delivery, not only at the end of a
chapter. Keep the ordered chapter table complete even when most chapters have not been read.

```markdown
# <novel-title>: progress

## Settings
16:9 · 768p · reference to video · Mandarin speech · cinematic realism
Chinese source subtitles + English translation · Chinese track default

## Chapter index
source/chapters.json · 24 verified chapters

## Chapters
| Chapter | Title | Status | Production folder | Final film | Next work |
| --- | --- | --- | --- | --- | --- |
| C001 | Arrival | done | chapters/C001/ | chapters/C001/Arrival.mp4 | — |
| C002 | The visitor | subtitling | chapters/C002/ | — | Review ASR, translate and mux |
| C003 | The letter | not_started | chapters/C003/ | — | Read and adapt |

## Next action
Resume C002 subtitle review using chapters/C002/jobs.json; do not resubmit its video jobs.
C002 is the earliest unfinished chapter. Start C003 after C002 delivery if further work is authorized.

## Shared references
refs/manifest.json · bible/cast.json · bible/locations.json
Lin adult_travel: C001–C002. New uniform needed when introduced; not generated yet.

## Continuity and open issues
C001 omitted a repeated carriage journey; arrival and possession of the letter were retained.
C002 consulted the first page of C003 to resolve the visitor's alias; do not reveal it early.

## Resume order
Progress → chapter index/status → shared bible and manifest → active chapter records/source → existing jobs.
```

Useful statuses: `not_started`, `adapting`, `storyboarded`, `references_ready`, `generating`, `qc`,
`assembled`, `subtitling`, `done`. Add a precise next action and error details when a stage fails; a status
alone is insufficient. An assembled chapter waiting for subtitles is unfinished and takes priority over the
next untouched chapter when continuing.

Keep changes to shared voices, identity and locations in `bible/changes.md`, including which completed
chapters used earlier versions. Once the authorized chapters are delivered, update the novel-wide video
index. A series poster or summary is optional; it must not delay delivery of an already completed chapter.
