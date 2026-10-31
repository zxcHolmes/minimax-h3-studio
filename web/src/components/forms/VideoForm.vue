<script setup>
import { useVideoPrompt } from '../../composables/useVideoPrompt'
import { fileFrom, useJobSubmission } from '../../composables/useGeneration'
import VideoModelSettings from './VideoModelSettings.vue'
import VideoPromptFields from './VideoPromptFields.vue'
import FormFooter from './FormFooter.vue'

import { computed, nextTick, ref, watch } from 'vue'
import ImageDrop from '../ImageDrop.vue'
import RefImages from '../RefImages.vue'

const props = defineProps({
  resolutions: Array, groups: Array, loras: Array, defaultLoras: Object, aspects: Array, durationRange: Array,
  maxRefs: Number, maxRefVideos: Number, strengthRange: Array, samplers: Array,
  ready: Boolean,
})
const emit = defineEmits(['created'])

// MiniMax-H3 prompts have three labelled sections; the form edits them separately.
// Reference mode wraps the same three in the ref2va layout (subjects, summary, retention).
const FAMILY = { t2v: 'fl2va', i2v: 'fl2va', r2v: 'ref2va' }
const STORAGE_KEY = 'h3.form.video'
const LEGACY_KEY = 'h3.form.v2'
const saved = (() => { try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || localStorage.getItem(LEGACY_KEY)) || {} } catch { return {} } })()

const mode = defineModel('mode', { default: 't2v' })
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
const duration = ref(saved.duration || 5)
const { seed, submitting, error, send } = useJobSubmission(emit)
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
// Reference videos follow the images: <Video k> is <Subject images + k>; its soundtrack goes in as <Audio k>.
const refVideos = ref([])
const imageSize = ref(null)

watch([mode, rawMode, sections, raw, resolution, group, lora, strength, sampler, aspect, duration], () => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      mode: mode.value, rawMode: rawMode.value, sections: sections.value, raw: raw.value,
      resolution: resolution.value, group: group.value, lora: lora.value, strength: strength.value, sampler: sampler.value, aspect: aspect.value, duration: duration.value,
    }))
  } catch { /* storage unavailable */ }
}, { deep: true })

watch(mode, (m) => {
  if (m !== 'i2v' && aspect.value === 'image') aspect.value = '16:9'
  if (m === 'i2v' && imageFile.value) aspect.value = 'image'
})

// The group and mode pick the base model; the list shows the choices that run on it at this resolution.
// H3 and Pika run a LoRA on the official bases; FastH3 bases are distilled and run on their own. Groups with no choice for the
// mode are hidden.
const groupOptions = computed(() => (props.groups || []).filter(
  (g) => (props.loras || []).some((l) => l.group === g.id && l.family === FAMILY[mode.value])).map(
  (g) => ({ ...g, lora: (props.loras || []).some((l) => l.group === g.id && l.models.lora) })))
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
// larryvrh, FastH3 and Pika keep the sampler they were distilled for.
const samplerChoosable = computed(() => !!currentLora.value && !currentLora.value.fixed && (props.samplers || []).includes(currentLora.value.models.sampler))
const effectiveSampler = computed(() => (samplerChoosable.value && sampler.value) || currentLora.value?.models.sampler)

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

const { prompt, hasContent, toggleRaw, loadPrompt } = useVideoPrompt({ mode, refs, refVideos, frames, rawMode, raw, sections, error })

// Measured on the RTX 4090 (int8 bases, kitchen CUDA + triton backends, sage): sampling seconds per step per second of
// video, plus encode/decode/save. Switching base model costs well under a second.
// FastH3 runs with sparse attention (VSA), which makes its steps cheaper.
const STEP_COST = {
  h3: { fl2va: { '544p': 0.85, '768p': 2.3 }, ref2va: { '544p': 0.95, '768p': 2.3 } },
  fasth3: { fl2va: { '544p': 0.65, '768p': 1.3 }, ref2va: { '544p': 0.7, '768p': 1.2 } },
  pika: { fl2va: { '544p': 0.85, '768p': 2.3 }, ref2va: { '544p': 1.2, '768p': 2.6 } },
}
const OVERHEAD = { '544p': 12, '768p': 20 }
// Sol-Attn sparse attention on Pika: sampling took ~55% of the dense time (both test shots).
const SPARSE_COST = 0.55
const estimate = computed(() => {
  const sparse = currentLora.value?.models.attention?.startsWith('Sol') ? SPARSE_COST : 1
  const cost = (STEP_COST[group.value]?.[FAMILY[mode.value]]?.[resolution.value] || 3.3) * sparse
  return Math.round((OVERHEAD[resolution.value] || 20) + cost * (currentLora.value?.steps || 4) * duration.value)
})

const canSubmit = computed(() => props.ready && !submitting.value && hasContent.value && (mode.value !== 'i2v' || !!imageFile.value))

watch(imageFile, (f) => {
  if (f) aspect.value = 'image'
  else if (aspect.value === 'image') aspect.value = '16:9'
})

function submit() {
  if (!canSubmit.value) return
  const form = new FormData()
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
  if (mode.value === 'r2v') {
    refs.value.forEach((r) => form.append('ref_image', r.file))
    refVideos.value.forEach((r) => form.append('ref_video', r.file))
  }
  if (audioFile.value) {
    form.append('audio', audioFile.value)
    form.append('audio_start', String(audioStart.value || 0))
  }
  return send(form)
}

// Load a past job's settings back into the form.
function reuse(job) {
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
    const videoUrls = job.ref_video_urls || []
    Promise.all([
      ...job.ref_urls.map((u, i) => fileFrom(u, job.refs[i])),
      ...videoUrls.map((u, i) => fileFrom(u, job.ref_videos[i])),
    ]).then((files) => {
      const n = job.ref_urls.length
      refs.value = files.slice(0, n).map((file, i) => ({ id: `reuse-${job.id}-${i}`, file, desc: descs[i] || '' }))
      refVideos.value = files.slice(n).map((file, i) => ({ id: `reuse-${job.id}-v${i}`, file, desc: descs[n + i] || '' }))
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
  <form class="generation-form" @submit.prevent="submit">
    <div v-if="mode === 'r2v'" class="field">
      <span class="field-label">Reference images<span class="aside">People, objects or places; image N is &lt;Subject N&gt;</span></span>
      <RefImages v-model="refs" :max="maxRefs || 6" />
    </div>

    <div v-if="mode === 'r2v'" class="field">
      <span class="field-label">Reference videos<span class="aside">Motion, camera or scene, with its sound</span></span>
      <RefImages v-model="refVideos" video :first="refs.length + 1" :max="maxRefVideos || 3" />
      <p v-if="refVideos.length" class="help">Each reference video multiplies the generation time (a 5 s clip at 544p: ~26 s → ~100 s).</p>
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

    <VideoPromptFields v-model:raw-mode="rawMode" v-model:raw="raw" v-model:sections="sections" :mode="mode" @toggle-raw="toggleRaw" />

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

    <VideoModelSettings
      v-model:resolution="resolution" v-model:lora="lora" v-model:strength="strength" v-model:sampler="sampler"
      :resolutions="resolutions" :group-options="groupOptions" :group="group" :lora-options="loraOptions"
      :recommended="recommended" :current-lora="currentLora" :strength-range="strengthRange"
      :sampler-choosable="samplerChoosable" :samplers="samplers" :effective-sampler="effectiveSampler"
      @pick-group="pickGroup"
    />

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

    <FormFooter v-model:seed="seed" :ready="ready" :submitting="submitting" :can-submit="canSubmit" :error="error" label="Generate video">
      <span v-if="outputSize" class="mono">{{ outputSize.join('×') }}</span><span class="muted">About {{ estimate }} s</span>
    </FormFooter>
  </form>
</template>
