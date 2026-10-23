<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { PhShuffle, PhTextAlignLeft, PhRows } from '@phosphor-icons/vue'
import { api } from '../api'
import { shortModel } from '../models'
import ImageDrop from './ImageDrop.vue'
import RefImages from './RefImages.vue'

const props = defineProps({
  resolutions: Array, groups: Array, loras: Array, defaultLoras: Object, aspects: Array, durationRange: Array,
  maxRefs: Number, strengthRange: Array, samplers: Array, picture: Object, music: Object,
  ready: Boolean,
})
const emit = defineEmits(['created'])

// MiniMax-H3 prompts have three labelled sections; the form edits them separately.
// Reference mode wraps the same three in the ref2va layout (subjects, summary, retention).
const SECTIONS = [
  { key: 'picture', tag: 'integrated_multimodal_description', label: 'Picture', rows: 6,
    help: 'Style, subject, action, camera and light. Put dialogue inline: <d>[English] Hello.</d>',
    refTag: 'detailed_description',
    refHelp: 'Refer to the reference subjects as <Subject 1>, <Subject 2>; describe action, camera and light. Put dialogue inline: <d>[English] Hello.</d>' },
  { key: 'sound', tag: 'overall_soundscape', label: 'Sound', rows: 2,
    help: 'Dialogue, ambience and sound effects.' },
  { key: 'score', tag: 'non_diegetic_music', label: 'Music', rows: 2,
    help: 'Background score. Leave empty for none.' },
]
const PICTURE_HINT = {
  t2v: 'Live-action, cinematic. A fisherman hauls a dripping net onto a wooden boat at sunrise...',
  i2v: 'Preserve the subject and scene from <Picture 1>, then describe the motion and camera...',
  r2v: 'Live-action, bright afternoon light. <Subject 1> rides <Subject 2> down a Paris street toward the camera...',
}
const SECTION_RE = /^\s*integrated_multimodal_description:\s*([\s\S]*?)\n\s*\n\s*overall_soundscape:\s*([\s\S]*?)\n\s*\n\s*non_diegetic_music:\s*([\s\S]*?)\s*$/
const REF_SECTION_RE = /\n\s*detailed_description:\s*([\s\S]*?)\n\s*\n\s*overall_soundscape:\s*([\s\S]*?)\n\s*\n\s*non_diegetic_music:\s*([\s\S]*?)\s*$/
const SUBJECT_RE = /^<Subject (\d+)> is ([\s\S]*?), as shown in <Picture \d+>\.$/gm
const FAMILY = { t2v: 'fl2va', i2v: 'fl2va', r2v: 'ref2va' }
const MUSIC_CAPTION_HINT = `Global Metadata: Lo-fi hip-hop, 78 BPM, D flat major. Laid-back and dreamy, late-night study mood.

Vocal Details: Soft androgynous vocal, hushed half-sung delivery, sitting low in the mix.

Arrangement: Dusty boom-bap drums, warm Rhodes chords, mellow jazzy guitar, vinyl crackle.`
const MUSIC_LYRICS_HINT = `[Intro]
Mmm...

[Verse]
Midnight and the canvas glows

[Chorus]
Let it render on

[Outro]
Ooh... goodnight`
const MODE_TABS = [['t2v', 'Text'], ['i2v', 'Frames'], ['r2v', 'Reference'], ['t2i', 'Picture'], ['t2m', 'Music']]

const STORAGE_KEY = 'h3.form.v2'
const saved = (() => { try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {} } catch { return {} } })()

const mode = ref(saved.mode || 't2v')
const rawMode = ref(saved.rawMode || false)
const sections = ref({ picture: '', sound: '', score: '', ...saved.sections })
const raw = ref(saved.raw || '')
// Older saved forms stored combined ids such as "ref-544p".
const resolution = ref((saved.resolution || saved.preset || '768p').replace('ref-', ''))
const group = ref(saved.group || 'h3')
const lora = ref(saved.lora || '')
const strength = ref(saved.strength ?? 1)
// '' runs the model choice's own sampler.
const sampler = ref(saved.sampler || '')
const aspect = ref(saved.aspect || '16:9')
// Picture mode keeps its own prompt and aspect so switching tabs leaves the video form intact.
const picPrompt = ref(saved.picPrompt || '')
const picAspect = ref(saved.picAspect || '1:1')
// Music keeps its caption, lyrics and length apart from the video form too.
const musicCaption = ref(saved.musicCaption || '')
const musicLyrics = ref(saved.musicLyrics || '')
const musicDuration = ref(saved.musicDuration || 120)
const duration = ref(saved.duration || 5)
const seed = ref('')
const imageFile = ref(null)
const lastFile = ref(null)
// Optional guide audio for video modes: the clip from audioStart is anchored as the shot's soundtrack.
const audioFile = ref(null)
const audioStart = ref(0)
const audioUrl = ref(null)
watch(audioFile, (f) => {
  if (audioUrl.value) URL.revokeObjectURL(audioUrl.value)
  audioUrl.value = f ? URL.createObjectURL(f) : null
})
function pickAudio(e) {
  const f = e.target.files?.[0]
  if (f) { audioFile.value = f; audioStart.value = 0 }
  e.target.value = ''
}
const refs = ref([])
const imageSize = ref(null)
const submitting = ref(false)
const error = ref('')

watch([mode, rawMode, sections, raw, resolution, group, lora, strength, sampler, aspect, duration, picPrompt, picAspect, musicCaption, musicLyrics, musicDuration], () => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      mode: mode.value, rawMode: rawMode.value, sections: sections.value, raw: raw.value,
      resolution: resolution.value, group: group.value, lora: lora.value, strength: strength.value, sampler: sampler.value, aspect: aspect.value, duration: duration.value,
      picPrompt: picPrompt.value, picAspect: picAspect.value,
      musicCaption: musicCaption.value, musicLyrics: musicLyrics.value, musicDuration: musicDuration.value,
    }))
  } catch { /* storage unavailable */ }
}, { deep: true })

watch(mode, (m) => {
  if (m !== 'i2v' && aspect.value === 'image') aspect.value = '16:9'
  if (m === 'i2v' && imageFile.value) aspect.value = 'image'
})

// The group and mode pick the base model; the list shows the choices that run on it at this resolution.
// H3 bases take a LoRA; FastH3 bases are distilled and run on their own. Groups with no choice for the
// mode are hidden (reference mode is FastH3 only).
const groupOptions = computed(() => (props.groups || []).filter(
  (g) => (props.loras || []).some((l) => l.group === g.id && l.family === FAMILY[mode.value])))
// The group the user picked; a mode that lacks it borrows another and gives it back afterwards.
const pickedGroup = ref(group.value)
function pickGroup(id) { group.value = id; pickedGroup.value = id }
watch(groupOptions, (opts) => {
  if (!opts.length) return
  if (opts.some((g) => g.id === pickedGroup.value)) group.value = pickedGroup.value
  else if (!opts.some((g) => g.id === group.value)) group.value = opts[0].id
}, { immediate: true })
const loraOptions = computed(() => (props.loras || []).filter(
  (l) => l.group === group.value && l.family === FAMILY[mode.value] && l.resolutions.includes(resolution.value)))
const recommended = computed(() => group.value === 'h3'
  ? props.defaultLoras?.[FAMILY[mode.value]]?.[resolution.value]
  : loraOptions.value[0]?.id)
watch([loraOptions, recommended], () => {
  if (loraOptions.value.length && !loraOptions.value.some((l) => l.id === lora.value)) lora.value = recommended.value
}, { immediate: true })
const currentLora = computed(() => props.loras?.find((l) => l.id === lora.value))
// larryvrh runs its own turbo sampler, which is not in the list.
const samplerChoosable = computed(() => !!currentLora.value && (props.samplers || []).includes(currentLora.value.models.sampler))
const effectiveSampler = computed(() => (samplerChoosable.value && sampler.value) || currentLora.value?.models.sampler)

function assemble(s) {
  return `integrated_multimodal_description: ${s.picture.trim()}\n\n` +
    `overall_soundscape: ${s.sound.trim() || 'N/A'}\n\n` +
    `non_diegetic_music: ${s.score.trim() || 'N/A'}`
}

// With no reference images the ref2va model runs on the prompt alone: no subjects to define or retain.
function assembleRef(s) {
  const tags = refs.value.map((_, i) => i + 1)
  const seconds = (frames.value / 24).toFixed(4)
  const names = tags.map((i) => `<Subject ${i}>`)
  const featuring = names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0]
  const subjects = tags.length
    ? 'subject_definitions:\n' +
      refs.value.map((r, i) => `<Subject ${i + 1}> is ${r.desc.trim() || 'the subject'}, as shown in <Picture ${i + 1}>.`).join('\n') + '\n\n'
    : ''
  const retention = tags.length
    ? '\n\nretention_analysis:\n' +
      tags.map((i) => `<Subject ${i}> (appears in [Shot 1]): fully_preserved - Preserve the same appearance as in <Picture ${i}>.`).join('\n')
    : ''
  return subjects +
    `summary:\n[reference generation] A continuous ${seconds}-second video` + (featuring ? ` featuring ${featuring}` : '') + ', as described below.' +
    retention +
    `\n\ndetailed_description:\n${s.picture.trim()}` +
    `\n\noverall_soundscape:\n${s.sound.trim() || 'N/A'}` +
    `\n\nnon_diegetic_music:\n${s.score.trim() || 'N/A'}`
}

// Split a prompt back into the form's sections; null when it is not in a layout the form writes.
function parse(text, m = mode.value) {
  const hit = m === 'r2v' ? text.match(REF_SECTION_RE) : text.match(SECTION_RE)
  if (!hit) return null
  const clean = (v) => (v.trim() === 'N/A' ? '' : v.trim())
  return {
    sections: { picture: hit[1].trim(), sound: clean(hit[2]), score: clean(hit[3]) },
    descs: m === 'r2v' ? [...text.matchAll(SUBJECT_RE)].map((x) => (x[2] === 'the subject' ? '' : x[2])) : [],
  }
}

const prompt = computed(() => {
  if (rawMode.value) return raw.value
  return mode.value === 'r2v' ? assembleRef(sections.value) : assemble(sections.value)
})
const hasContent = computed(() => (rawMode.value ? raw.value.trim() : sections.value.picture.trim()))

function applyDescs(descs) {
  descs.forEach((d, i) => { if (refs.value[i]) refs.value[i].desc = d })
}

function toggleRaw() {
  if (!rawMode.value) {
    raw.value = hasContent.value ? prompt.value : ''
    rawMode.value = true
    return
  }
  const parsed = raw.value.trim() ? parse(raw.value) : { sections: { picture: '', sound: '', score: '' }, descs: [] }
  if (parsed) {
    sections.value = parsed.sections
    applyDescs(parsed.descs)
    rawMode.value = false
  } else {
    error.value = 'This prompt does not follow the section layout; keep editing it as a raw prompt.'
  }
}

function loadPrompt(text, m) {
  const parsed = parse(text, m)
  if (parsed) {
    sections.value = parsed.sections
    rawMode.value = false
  } else {
    raw.value = text
    rawMode.value = true
  }
  return parsed?.descs || []
}

const aspectOptions = computed(() => (mode.value === 'i2v' ? ['image', ...(props.aspects || [])] : props.aspects || []))
const currentRes = computed(() => props.resolutions?.find((r) => r.id === resolution.value))

function roundTo32(v) { return Math.max(32, Math.round(v / 32) * 32) }

const outputSize = computed(() => {
  const p = currentRes.value
  if (!p) return null
  if (aspect.value === 'image') {
    if (!imageSize.value) return null
    const [w, h] = p.sizes['16:9']
    const r = imageSize.value.w / imageSize.value.h
    return [roundTo32(Math.sqrt(w * h * r)), roundTo32(Math.sqrt((w * h) / r))]
  }
  return p.sizes[aspect.value]
})

// The model renders 17k+5 frames at 24 fps; show what a duration actually becomes.
const frames = computed(() => {
  let n = Math.max(5, Math.round(duration.value * 24))
  while (n % 17 !== 5) n += 1
  return n
})
const timecode = computed(() => {
  const s = Math.floor(frames.value / 24)
  const f = frames.value % 24
  return `00:00:${String(s).padStart(2, '0')}:${String(f).padStart(2, '0')}`
})
const ticks = computed(() => {
  const [lo, hi] = props.durationRange || [2, 15]
  return Array.from({ length: hi - lo + 1 }, (_, i) => lo + i)
})

// Measured on the RTX 4090 (int8 bases, kitchen CUDA + triton backends, sage): sampling seconds per step per second of
// video, plus encode/decode/save. Switching base model costs well under a second.
// FastH3 runs with sparse attention (VSA), which makes its steps cheaper.
const STEP_COST = {
  h3: { fl2va: { '544p': 0.85, '768p': 2.3 }, ref2va: { '544p': 0.95, '768p': 2.3 } },
  fasth3: { fl2va: { '544p': 0.65, '768p': 1.3 }, ref2va: { '544p': 0.7, '768p': 1.2 } },
}
const OVERHEAD = { '544p': 12, '768p': 20 }
const estimate = computed(() => {
  const cost = STEP_COST[group.value]?.[FAMILY[mode.value]]?.[resolution.value] || 3.3
  return Math.round((OVERHEAD[resolution.value] || 20) + cost * (currentLora.value?.steps || 4) * duration.value)
})

const isPicture = computed(() => mode.value === 't2i')
const pictureSize = computed(() => props.picture?.sizes?.[picAspect.value])
// Measured on the RTX 4090: 25 steps at about one megapixel.
const pictureEstimate = 16

const isMusic = computed(() => mode.value === 't2m')
const musicRange = computed(() => props.music?.duration_range || [10, 300])
function clock(s) { return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}` }
const musicLength = computed(() => clock(musicDuration.value))
// Rough length the lyrics need: about 0.6 s per sung Chinese character (or English word), a few seconds
// per section for breaths and fills, plus intro and outro. The duration is only a cap, so err long.
const lyricsNeed = computed(() => {
  const text = musicLyrics.value
  const sections = (text.match(/\[[^\]]+\]/g) || []).length
  const sung = text.replace(/\[[^\]]+\]/g, '')
  const units = (sung.match(/[\u3400-\u9fff]/g) || []).length + (sung.match(/[A-Za-z']+/g) || []).length
  if (!units) return null
  const [lo, hi] = musicRange.value
  return Math.min(hi, Math.max(lo, Math.ceil((units * 0.6 + sections * 4 + 15) / 10) * 10))
})
const lyricsTooShort = computed(() => lyricsNeed.value !== null && musicDuration.value < lyricsNeed.value)
// Measured on the RTX 4090: writing the acoustic tokens dominates and grows with the song length.
const MUSIC_SECONDS_PER_SECOND = 1.3
const musicEstimate = computed(() => Math.round(20 + MUSIC_SECONDS_PER_SECOND * musicDuration.value))

const canSubmit = computed(() => props.ready && !submitting.value && (
  isPicture.value ? !!picPrompt.value.trim()
    : isMusic.value ? !!musicCaption.value.trim()
      : hasContent.value && (mode.value === 't2v' || (mode.value === 'i2v' && imageFile.value) || mode.value === 'r2v')))

watch(imageFile, (f) => {
  if (f) aspect.value = 'image'
  else if (aspect.value === 'image') aspect.value = '16:9'
})

async function fileFrom(url, name) {
  const blob = await (await fetch(url)).blob()
  return new File([blob], name, { type: blob.type })
}

function randomSeed() {
  seed.value = String(Math.floor(Math.random() * 2 ** 40))
}

async function submit() {
  error.value = ''
  submitting.value = true
  try {
    const form = new FormData()
    if (isPicture.value) {
      form.append('kind', 'image')
      form.append('prompt', picPrompt.value)
      form.append('aspect_ratio', picAspect.value)
      if (seed.value.trim()) form.append('seed', seed.value.trim())
      emit('created', await api.create(form))
      return
    }
    if (isMusic.value) {
      form.append('kind', 'music')
      form.append('prompt', musicCaption.value)
      form.append('lyrics', musicLyrics.value)
      form.append('duration', String(musicDuration.value))
      if (seed.value.trim()) form.append('seed', seed.value.trim())
      emit('created', await api.create(form))
      return
    }
    form.append('prompt', prompt.value)
    form.append('resolution', resolution.value)
    form.append('lora', lora.value)
    if (currentLora.value?.models.lora) form.append('lora_strength', String(strength.value))
    if (samplerChoosable.value && sampler.value) form.append('sampler', sampler.value)
    form.append('aspect_ratio', aspect.value)
    form.append('duration', String(duration.value))
    if (seed.value.trim()) form.append('seed', seed.value.trim())
    if (mode.value === 'i2v' && imageFile.value) {
      form.append('image', imageFile.value)
      if (lastFile.value) form.append('last_image', lastFile.value)
    }
    if (mode.value === 'r2v') refs.value.forEach((r) => form.append('ref_image', r.file))
    if (audioFile.value) {
      form.append('audio', audioFile.value)
      form.append('audio_start', String(audioStart.value || 0))
    }
    emit('created', await api.create(form))
  } catch (e) {
    error.value = e.message
  } finally {
    submitting.value = false
  }
}

// Load a past job's settings back into the form.
function reuse(job) {
  if (job.mode === 't2i') {
    mode.value = 't2i'
    picPrompt.value = job.prompt
    seed.value = String(job.seed)
    const match = Object.entries(props.picture?.sizes || {}).find(([, s]) => s[0] === job.width && s[1] === job.height)
    if (match) picAspect.value = match[0]
    return
  }
  if (job.mode === 't2m') {
    mode.value = 't2m'
    musicCaption.value = job.prompt
    musicLyrics.value = job.lyrics || ''
    musicDuration.value = Math.round(job.duration)
    seed.value = String(job.seed)
    return
  }
  const descs = loadPrompt(job.prompt, job.mode === 'r2v' ? 'r2v' : 'i2v')
  audioFile.value = null
  if (job.guide_audio_url) {
    fileFrom(job.guide_audio_url, job.guide_audio).then((f) => { audioFile.value = f; audioStart.value = job.audio_start || 0 })
  }
  resolution.value = job.preset
  duration.value = job.duration
  seed.value = String(job.seed)
  const choice = props.loras?.find((l) => l.id === job.lora)
  if (choice) pickGroup(choice.group)
  // After the mode watcher has reset the LoRA list for the reused job's mode.
  nextTick(() => { if (choice) lora.value = job.lora })
  strength.value = job.lora_strength ?? 1
  sampler.value = job.sampler || ''
  const sizes = props.resolutions?.find((r) => r.id === job.preset)?.sizes || {}
  const match = Object.entries(sizes).find(([, s]) => s[0] === job.width && s[1] === job.height)
  if (job.mode === 'r2v') {
    mode.value = 'r2v'
    aspect.value = match ? match[0] : '16:9'
    Promise.all(job.ref_urls.map((u, i) => fileFrom(u, job.refs[i]))).then((files) => {
      refs.value = files.map((file, i) => ({ id: `reuse-${job.id}-${i}`, file, desc: descs[i] || '' }))
    })
  } else if (job.image_url) {
    mode.value = 'i2v'
    Promise.all([
      fileFrom(job.image_url, job.image),
      job.last_image_url ? fileFrom(job.last_image_url, job.last_image) : null,
    ]).then(([first, last]) => {
      imageFile.value = first
      lastFile.value = last
      aspect.value = match ? match[0] : 'image'
    })
  } else {
    mode.value = 't2v'
    imageFile.value = lastFile.value = null
    aspect.value = match ? match[0] : '16:9'
  }
}

// Send a finished picture into a video mode.
async function useAsRef(job) {
  const file = await fileFrom(job.picture_url, job.picture)
  mode.value = 'r2v'
  if (refs.value.length >= (props.maxRefs || 6)) {
    error.value = `At most ${props.maxRefs || 6} reference images; remove one first.`
    return
  }
  refs.value = [...refs.value, { id: `pic-${job.id}-${Date.now()}`, file, desc: '' }]
}

async function useAsFrame(job) {
  imageFile.value = await fileFrom(job.picture_url, job.picture)
  mode.value = 'i2v'
}

// Send a finished song into the video form as its guide audio.
async function useAsAudio(job) {
  audioFile.value = await fileFrom(job.audio_url, `${job.id}.mp3`)
  audioStart.value = 0
  if (mode.value === 't2i' || mode.value === 't2m') mode.value = 't2v'
}

defineExpose({ reuse, useAsRef, useAsFrame, useAsAudio })
</script>

<template>
  <form class="form" @submit.prevent="submit">
    <div class="modes" role="tablist" aria-label="Generation mode">
      <button
        v-for="[id, label] in MODE_TABS"
        :key="id"
        type="button"
        role="tab"
        :aria-selected="mode === id"
        :class="{ on: mode === id }"
        @click="mode = id"
      >{{ label }}</button>
    </div>

    <template v-if="isPicture">
      <div class="field">
        <label for="pic-prompt" class="field-label">Prompt</label>
        <textarea
          id="pic-prompt"
          v-model="picPrompt"
          class="textarea"
          rows="7"
          spellcheck="false"
          placeholder="3D animated film style, a lion cub with a red mane, full body, front view, plain white background"
        />
        <p class="help">Describe subject, style, framing and background; a plain background works best for reference images.</p>
      </div>

      <div class="field">
        <span class="field-label">Aspect ratio</span>
        <div class="chips">
          <button
            v-for="a in aspects"
            :key="a"
            type="button"
            class="chip"
            :class="{ on: picAspect === a }"
            :aria-pressed="picAspect === a"
            @click="picAspect = a"
          >{{ a }}</button>
        </div>
        <dl v-if="picture" class="models">
          <div><dt>Model</dt><dd class="mono" :title="picture.models.unet">{{ shortModel(picture.models.unet) }}</dd></div>
          <div><dt>Sampler</dt><dd class="mono">{{ picture.models.sampler }} · {{ picture.models.steps }} steps · cfg {{ picture.models.cfg }}</dd></div>
        </dl>
      </div>
    </template>

    <template v-else-if="isMusic">
      <div class="field">
        <label for="music-caption" class="field-label">Caption<span class="aside">Style, mood, vocals, arrangement</span></label>
        <textarea
          id="music-caption"
          v-model="musicCaption"
          class="textarea"
          rows="8"
          spellcheck="false"
          :placeholder="MUSIC_CAPTION_HINT"
        />
        <p class="help">Write three parts: Global Metadata (genre, BPM, key, mood), Vocal Details and Arrangement. The more specific, the closer the result.</p>
      </div>

      <div class="field">
        <label for="music-lyrics" class="field-label">Lyrics<span class="aside">Empty for an instrumental</span></label>
        <textarea
          id="music-lyrics"
          v-model="musicLyrics"
          class="textarea mono raw"
          rows="10"
          spellcheck="false"
          :placeholder="MUSIC_LYRICS_HINT"
        />
        <p class="help">Section tags such as [Intro], [Verse], [Chorus], [Bridge], [Instrumental] and [Outro] set the song structure.</p>
      </div>

      <div class="field">
        <label for="music-duration" class="field-label">
          <span>Maximum length</span>
          <span class="aside mono">{{ musicLength }}</span>
        </label>
        <input
          id="music-duration"
          v-model.number="musicDuration"
          class="range"
          type="range"
          :min="musicRange[0]"
          :max="musicRange[1]"
          step="10"
        />
        <p v-if="lyricsTooShort" class="help warn">
          The lyrics need about {{ clock(lyricsNeed) }}; at {{ musicLength }} the song will be cut off.
          <button type="button" class="btn quiet small" @click="musicDuration = lyricsNeed">Use {{ clock(lyricsNeed) }}</button>
        </p>
        <p v-else class="help">The model may end the song earlier.<template v-if="lyricsNeed"> The lyrics need about {{ clock(lyricsNeed) }}.</template></p>
        <dl v-if="music" class="models">
          <div><dt>Model</dt><dd class="mono" :title="music.models.unet">{{ shortModel(music.models.unet) }}</dd></div>
          <div><dt>Sampler</dt><dd class="mono">{{ music.models.sampler }} · {{ music.models.steps }} steps · cfg {{ music.models.cfg }}</dd></div>
        </dl>
      </div>
    </template>

    <template v-else>
    <div v-if="mode === 'r2v'" class="field">
      <span class="field-label">Reference images<span class="aside">People, objects or places; image N is &lt;Subject N&gt;</span></span>
      <RefImages v-model="refs" :max="maxRefs || 6" />
    </div>

    <div v-if="mode === 'i2v'" class="field">
      <span class="field-label">Keyframes<span class="aside">Add a last frame to move between the two</span></span>
      <div class="keyframes">
        <div class="keyframe">
          <span class="kf-label">First frame</span>
          <ImageDrop v-model="imageFile" label="first frame" placeholder="Drop or click to choose" @size="imageSize = $event" />
        </div>
        <div class="keyframe">
          <span class="kf-label">Last frame <span class="muted">(optional)</span></span>
          <ImageDrop v-model="lastFile" label="last frame" placeholder="Drop or click to choose" />
        </div>
      </div>
      <p v-if="lastFile && !imageFile" class="help warn">A last frame needs a first frame.</p>
    </div>

    <div class="field">
      <div class="field-label">
        <span>Prompt</span>
        <button type="button" class="btn quiet small" @click="toggleRaw">
          <component :is="rawMode ? PhRows : PhTextAlignLeft" :size="14" />
          {{ rawMode ? 'Sections' : 'Raw prompt' }}
        </button>
      </div>

      <textarea
        v-if="rawMode"
        v-model="raw"
        class="textarea mono raw"
        rows="12"
        spellcheck="false"
        aria-label="Raw prompt"
        placeholder="integrated_multimodal_description: ..."
      />
      <div v-else class="sections">
        <div v-for="s in SECTIONS" :key="s.key" class="section">
          <label :for="`sec-${s.key}`" class="section-label">
            {{ s.label }}<span class="mono tag">{{ mode === 'r2v' && s.refTag ? s.refTag : s.tag }}</span>
          </label>
          <textarea
            :id="`sec-${s.key}`"
            v-model="sections[s.key]"
            class="textarea"
            :rows="s.rows"
            spellcheck="false"
            :placeholder="s.key === 'picture' ? PICTURE_HINT[mode] : ''"
          />
          <p class="help">{{ mode === 'r2v' && s.refHelp ? s.refHelp : s.help }}</p>
        </div>
      </div>
      <p v-if="mode === 'i2v'" class="help">The first frame is &lt;Picture 1&gt; and the last frame &lt;Picture 2&gt;; the server adds these references if the prompt lacks them.</p>
      <p v-if="mode === 'r2v' && !rawMode" class="help">Subject definitions, summary and retention notes are generated from the images; open the raw prompt to see the full text.</p>
    </div>

    <div class="field">
      <span class="field-label">Guide audio<span class="aside">Optional; the shot is generated to match it</span></span>
      <div v-if="audioFile" class="guide">
        <audio :src="audioUrl" controls preload="metadata" />
        <div class="guide-row">
          <span class="mono guide-name" :title="audioFile.name">{{ audioFile.name }}</span>
          <label class="guide-start">
            Start at
            <input v-model.number="audioStart" class="input mono" type="number" min="0" step="0.1" />
            s
          </label>
          <button type="button" class="btn quiet small" @click="audioFile = null">Remove</button>
        </div>
        <p class="help">The {{ (frames / 24).toFixed(2) }} s from this point become the shot's soundtrack; singing and speech drive the mouths and motion.</p>
      </div>
      <label v-else class="btn guide-pick">
        Choose an audio file
        <input type="file" accept="audio/*" class="sr-only" @change="pickAudio" />
      </label>
    </div>

    <div class="field">
      <span class="field-label">Resolution</span>
      <div class="presets">
        <button
          v-for="r in resolutions"
          :key="r.id"
          type="button"
          class="preset"
          :class="{ on: resolution === r.id }"
          :aria-pressed="resolution === r.id"
          @click="resolution = r.id"
        >
          <span class="preset-name">{{ r.id }}</span>
          <span class="preset-meta mono">{{ r.sizes['16:9'].join('×') }}</span>
        </button>
      </div>
    </div>

    <div class="field">
      <span class="field-label">Model<span class="aside">The base model follows the mode</span></span>
      <div class="presets groups">
        <button
          v-for="g in groupOptions"
          :key="g.id"
          type="button"
          class="preset"
          :class="{ on: group === g.id }"
          :aria-pressed="group === g.id"
          @click="pickGroup(g.id)"
        >
          <span class="preset-name">{{ g.label }}</span>
          <span class="preset-meta mono">{{ g.id === 'h3' ? 'base + LoRA' : 'distilled, no LoRA' }}</span>
        </button>
      </div>
      <div class="loras" role="radiogroup" :aria-label="group === 'h3' ? 'LoRA' : 'Model'">
        <button
          v-for="l in loraOptions"
          :key="l.id"
          type="button"
          role="radio"
          class="lora"
          :class="{ on: lora === l.id }"
          :aria-checked="lora === l.id"
          @click="lora = l.id"
        >
          <span class="lora-name">{{ l.label }}<span v-if="l.id === recommended" class="pill">Recommended</span></span>
          <span class="lora-meta mono">{{ l.steps }} steps</span>
        </button>
      </div>
      <div v-if="currentLora?.models.lora" class="strength">
        <label for="strength" class="section-label">LoRA strength</label>
        <input
          id="strength"
          v-model.number="strength"
          type="range"
          :min="strengthRange?.[0] ?? 0"
          :max="strengthRange?.[1] ?? 2"
          step="0.05"
        />
        <span class="mono strength-value">{{ strength.toFixed(2) }}</span>
        <button v-if="strength !== 1" type="button" class="btn quiet small" @click="strength = 1">Reset</button>
      </div>
      <div v-if="samplerChoosable" class="sampler">
        <span class="section-label">Sampler</span>
        <div class="chips">
          <button
            v-for="s in samplers"
            :key="s"
            type="button"
            class="chip"
            :class="{ on: effectiveSampler === s }"
            :aria-pressed="effectiveSampler === s"
            @click="sampler = s === currentLora.models.sampler ? '' : s"
          >{{ s }}<template v-if="s === currentLora.models.sampler"> (default)</template></button>
        </div>
      </div>
      <dl v-if="currentLora" class="models">
        <div><dt>Base</dt><dd class="mono" :title="currentLora.models.unet">{{ shortModel(currentLora.models.unet) }}</dd></div>
        <div v-if="currentLora.models.lora"><dt>LoRA</dt><dd class="mono" :title="currentLora.models.lora">{{ shortModel(currentLora.models.lora) }} × {{ strength.toFixed(2) }}</dd></div>
        <div>
          <dt>Sampler</dt>
          <dd class="mono">{{ effectiveSampler }} · {{ currentLora.steps }} steps · shift {{ currentLora.models.shift_video }}/{{ currentLora.models.shift_audio }}</dd>
        </div>
        <div v-if="currentLora.models.attention"><dt>Attn</dt><dd class="mono">{{ currentLora.models.attention }}</dd></div>
      </dl>
    </div>

    <div class="field">
      <span class="field-label">Aspect ratio</span>
      <div class="chips">
        <button
          v-for="a in aspectOptions"
          :key="a"
          type="button"
          class="chip"
          :class="{ on: aspect === a }"
          :aria-pressed="aspect === a"
          :disabled="a === 'image' && !imageFile"
          @click="aspect = a"
        >{{ a === 'image' ? 'Match image' : a }}</button>
      </div>
    </div>

    <div class="field">
      <label for="duration" class="field-label">
        <span>Duration</span>
        <span class="aside mono">{{ frames }} frames / {{ timecode }}</span>
      </label>
      <div class="timeline">
        <input
          id="duration"
          v-model.number="duration"
          type="range"
          :min="ticks[0]"
          :max="ticks[ticks.length - 1]"
          step="1"
        />
        <div class="ruler" aria-hidden="true">
          <span v-for="t in ticks" :key="t" :class="{ major: t % 5 === 0, on: t === duration }">
            <i />
            <em v-if="t % 5 === 0 || t === ticks[0] || t === duration">{{ t }}s</em>
          </span>
        </div>
      </div>
    </div>
    </template>

    <div class="field">
      <label for="seed" class="field-label">Seed<span class="aside">Empty for random</span></label>
      <div class="seed">
        <input id="seed" v-model="seed" class="input mono" type="text" inputmode="numeric" placeholder="Random" />
        <button type="button" class="btn icon" aria-label="Pick a random seed" @click="randomSeed">
          <PhShuffle :size="16" />
        </button>
      </div>
    </div>

    <div class="submit">
      <span class="estimate">
        <template v-if="isPicture">
          <span v-if="pictureSize" class="mono">{{ pictureSize[0] }}×{{ pictureSize[1] }}</span>
          <span class="muted">About {{ pictureEstimate }} s</span>
        </template>
        <template v-else-if="isMusic">
          <span class="mono">≤ {{ musicLength }}</span>
          <span class="muted">About {{ musicEstimate }} s</span>
        </template>
        <template v-else>
          <span v-if="outputSize" class="mono">{{ outputSize[0] }}×{{ outputSize[1] }}</span>
          <span class="muted">About {{ estimate }} s</span>
        </template>
      </span>
      <button class="btn primary go" :disabled="!canSubmit">{{ submitting ? 'Submitting' : isPicture ? 'Generate picture' : isMusic ? 'Generate music' : 'Generate video' }}</button>
    </div>
    <p v-if="!ready" class="help">The server is still loading models; you can submit once it is ready.</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
  </form>
</template>

<style scoped>
.form { display: flex; flex-direction: column; gap: 22px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.small { padding: 3px 10px; font-size: 12px; }

.modes {
  display: grid; grid-template-columns: repeat(5, 1fr); gap: 4px; padding: 4px;
  background: var(--surface-sunk); border-radius: 999px;
}
.modes button {
  border: none; background: transparent; border-radius: 999px; padding: 7px 10px;
  font-weight: 500; color: var(--text-2); cursor: pointer; transition: background .15s, color .15s;
}
.modes button.on { background: var(--surface); color: var(--text); box-shadow: var(--shadow); }

.keyframes { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.keyframe { display: flex; flex-direction: column; gap: 6px; }
.kf-label { font-size: 12px; font-weight: 600; }
.help.warn { color: var(--live); }

.sections { display: flex; flex-direction: column; gap: 14px; }
.section { display: flex; flex-direction: column; gap: 6px; }
.section-label { display: flex; align-items: baseline; gap: 8px; font-size: 13px; font-weight: 600; }
.tag { font-size: 10.5px; font-weight: 400; color: var(--muted); }
.raw { font-size: 12.5px; }

.presets { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.preset {
  display: flex; flex-direction: column; align-items: flex-start; gap: 2px; text-align: left;
  padding: 11px 14px; border-radius: var(--r-card); border: 1px solid var(--line);
  background: var(--surface); cursor: pointer; transition: border-color .15s, background .15s;
}
.preset:hover { border-color: var(--muted); }
.preset.on { border-color: var(--accent); background: var(--accent-soft); }
.preset-name { font-size: 17px; font-weight: 650; letter-spacing: -.01em; }
.preset-meta { font-size: 11.5px; color: var(--muted); }
.groups { margin-bottom: 8px; }
.strength { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
.strength .section-label { margin: 0; white-space: nowrap; }
.strength input { flex: 1; min-width: 0; margin: 0; accent-color: var(--accent); }
.sampler { display: flex; align-items: center; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
.sampler .section-label { margin: 0; white-space: nowrap; }
.strength-value { font-size: 12px; color: var(--text-2); min-width: 32px; text-align: right; }
.groups .preset-name { font-size: 13.5px; font-weight: 600; }
.loras { display: flex; flex-direction: column; gap: 6px; }
.lora {
  display: flex; align-items: center; justify-content: space-between; gap: 8px; text-align: left;
  padding: 9px 14px; border-radius: var(--r-input); border: 1px solid var(--line);
  background: var(--surface); cursor: pointer; transition: border-color .15s, background .15s;
}
.lora:hover { border-color: var(--muted); }
.lora.on { border-color: var(--accent); background: var(--accent-soft); }
.lora-name { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 550; }
.lora-meta { font-size: 11.5px; color: var(--muted); }
.pill {
  font-size: 10.5px; font-weight: 500; color: var(--accent); border: 1px solid currentColor;
  border-radius: 999px; padding: 0 6px; line-height: 16px;
}
.models {
  margin: 0; padding: 10px 12px; border-radius: var(--r-input); background: var(--surface-sunk);
  display: flex; flex-direction: column; gap: 5px;
}
.models div { display: grid; grid-template-columns: 40px 1fr; gap: 8px; align-items: baseline; min-width: 0; }
.models dt { font-size: 11.5px; color: var(--muted); }
.models dd { margin: 0; font-size: 11.5px; color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  border: 1px solid var(--line); background: var(--surface); border-radius: 999px;
  padding: 4px 12px; font-size: 12.5px; cursor: pointer; transition: border-color .15s, color .15s;
}
.chip:hover:not(:disabled) { border-color: var(--muted); }
.chip.on { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.chip:disabled { opacity: .4; cursor: not-allowed; }

.timeline { position: relative; padding-top: 2px; }
.range { width: 100%; margin: 0; accent-color: var(--accent); }
.guide { display: flex; flex-direction: column; gap: 8px; }
.guide audio { width: 100%; }
.guide-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.guide-name { flex: 1; min-width: 0; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.guide-start { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; }
.guide-start .input { width: 84px; padding: 4px 8px; }
.guide-pick { align-self: flex-start; cursor: pointer; }
.timeline input { width: 100%; margin: 0; accent-color: var(--accent); }
.ruler { display: flex; justify-content: space-between; padding: 0 7px; margin-top: 4px; }
.ruler span { position: relative; width: 0; display: flex; flex-direction: column; align-items: center; }
.ruler i { width: 1px; height: 5px; background: var(--line); }
.ruler .major i { height: 9px; background: var(--muted); }
.ruler .on i { background: var(--accent); height: 9px; width: 2px; }
.ruler em {
  font-style: normal; font-size: 10.5px; color: var(--muted); margin-top: 3px;
  font-family: var(--font-mono); white-space: nowrap;
}
.ruler .on em { color: var(--accent); font-weight: 600; }

.seed { display: flex; gap: 8px; }

.submit {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding-top: 18px; border-top: 1px solid var(--line);
}
.estimate { display: flex; flex-direction: column; font-size: 12.5px; line-height: 1.4; }
.go { padding: 10px 26px; font-size: 14px; }
.error { color: var(--live); margin: 0; font-size: 13px; }
</style>
