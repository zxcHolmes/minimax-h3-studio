<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { PhShuffle, PhTextAlignLeft, PhRows } from '@phosphor-icons/vue'
import { api } from '../api'
import { shortModel } from '../models'
import ImageDrop from './ImageDrop.vue'
import RefImages from './RefImages.vue'

const props = defineProps({
  resolutions: Array, loras: Array, defaultLoras: Object, aspects: Array, durationRange: Array, maxRefs: Number,
  ready: Boolean,
})
const emit = defineEmits(['created'])

// MiniMax-H3 prompts have three labelled sections; the form edits them separately.
// Reference mode wraps the same three in the ref2va layout (subjects, summary, retention).
const SECTIONS = [
  { key: 'picture', tag: 'integrated_multimodal_description', label: '画面', rows: 6,
    help: '风格、主体、动作、镜头和光线。台词写在行内：<d>[English] Hello.</d>',
    refTag: 'detailed_description',
    refHelp: '用 <Subject 1>、<Subject 2> 指代参考图里的主体，写清动作、镜头和光线。台词写在行内：<d>[English] Hello.</d>' },
  { key: 'sound', tag: 'overall_soundscape', label: '声音', rows: 2,
    help: '对白、环境声和同步音效。' },
  { key: 'score', tag: 'non_diegetic_music', label: '配乐', rows: 2,
    help: '背景音乐。不需要就留空。' },
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

const STORAGE_KEY = 'h3.form.v2'
const saved = (() => { try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {} } catch { return {} } })()

const mode = ref(saved.mode || 't2v')
const rawMode = ref(saved.rawMode || false)
const sections = ref({ picture: '', sound: '', score: '', ...saved.sections })
const raw = ref(saved.raw || '')
// Older saved forms stored combined ids such as "ref-544p".
const resolution = ref((saved.resolution || saved.preset || '768p').replace('ref-', ''))
const lora = ref(saved.lora || '')
const aspect = ref(saved.aspect || '16:9')
const duration = ref(saved.duration || 5)
const seed = ref('')
const imageFile = ref(null)
const lastFile = ref(null)
const refs = ref([])
const imageSize = ref(null)
const submitting = ref(false)
const error = ref('')

watch([mode, rawMode, sections, raw, resolution, lora, aspect, duration], () => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      mode: mode.value, rawMode: rawMode.value, sections: sections.value, raw: raw.value,
      resolution: resolution.value, lora: lora.value, aspect: aspect.value, duration: duration.value,
    }))
  } catch { /* storage unavailable */ }
}, { deep: true })

watch(mode, (m) => {
  if (m !== 'i2v' && aspect.value === 'image') aspect.value = '16:9'
  if (m === 'i2v' && imageFile.value) aspect.value = 'image'
})

// The mode picks the base model; the LoRA list shows what runs on it at this resolution.
const loraOptions = computed(() => (props.loras || []).filter(
  (l) => l.family === FAMILY[mode.value] && l.resolutions.includes(resolution.value)))
const recommended = computed(() => props.defaultLoras?.[FAMILY[mode.value]]?.[resolution.value])
watch([loraOptions, recommended], () => {
  if (loraOptions.value.length && !loraOptions.value.some((l) => l.id === lora.value)) lora.value = recommended.value
}, { immediate: true })
const currentLora = computed(() => props.loras?.find((l) => l.id === lora.value))

function assemble(s) {
  return `integrated_multimodal_description: ${s.picture.trim()}\n\n` +
    `overall_soundscape: ${s.sound.trim() || 'N/A'}\n\n` +
    `non_diegetic_music: ${s.score.trim() || 'N/A'}`
}

function assembleRef(s) {
  const tags = refs.value.map((_, i) => i + 1)
  const seconds = (frames.value / 24).toFixed(4)
  const names = tags.map((i) => `<Subject ${i}>`)
  const featuring = names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0]
  return 'subject_definitions:\n' +
    refs.value.map((r, i) => `<Subject ${i + 1}> is ${r.desc.trim() || 'the subject'}, as shown in <Picture ${i + 1}>.`).join('\n') +
    `\n\nsummary:\n[reference generation] A continuous ${seconds}-second video featuring ${featuring || 'the referenced subjects'}, as described below.` +
    '\n\nretention_analysis:\n' +
    tags.map((i) => `<Subject ${i}> (appears in [Shot 1]): fully_preserved - Preserve the same appearance as in <Picture ${i}>.`).join('\n') +
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
    error.value = '这段提示词的格式没法拆回分段，请继续用原始模式编辑。'
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

// Measured on the RTX 4090 (int8 bases, triton + sage): sampling seconds per step per second of
// video, plus encode/decode/save. Switching base model costs well under a second.
const STEP_COST = { fl2va: { '544p': 1.1, '768p': 3.3 }, ref2va: { '544p': 1.5, '768p': 4 } }
const OVERHEAD = { '544p': 12, '768p': 20 }
const estimate = computed(() => {
  const cost = STEP_COST[FAMILY[mode.value]][resolution.value] || 3.3
  return Math.round((OVERHEAD[resolution.value] || 20) + cost * (currentLora.value?.steps || 4) * duration.value)
})

const canSubmit = computed(() => props.ready && !submitting.value && hasContent.value && (
  mode.value === 't2v' || (mode.value === 'i2v' && imageFile.value) || (mode.value === 'r2v' && refs.value.length)))

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
    form.append('prompt', prompt.value)
    form.append('resolution', resolution.value)
    form.append('lora', lora.value)
    form.append('aspect_ratio', aspect.value)
    form.append('duration', String(duration.value))
    if (seed.value.trim()) form.append('seed', seed.value.trim())
    if (mode.value === 'i2v' && imageFile.value) {
      form.append('image', imageFile.value)
      if (lastFile.value) form.append('last_image', lastFile.value)
    }
    if (mode.value === 'r2v') refs.value.forEach((r) => form.append('ref_image', r.file))
    emit('created', await api.create(form))
  } catch (e) {
    error.value = e.message
  } finally {
    submitting.value = false
  }
}

// Load a past job's settings back into the form.
function reuse(job) {
  const descs = loadPrompt(job.prompt, job.mode === 'r2v' ? 'r2v' : 'i2v')
  resolution.value = job.preset
  duration.value = job.duration
  seed.value = String(job.seed)
  // After the mode watcher has reset the LoRA list for the reused job's mode.
  nextTick(() => { if (job.lora) lora.value = job.lora })
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

defineExpose({ reuse })
</script>

<template>
  <form class="form" @submit.prevent="submit">
    <div class="modes" role="tablist" aria-label="生成方式">
      <button type="button" role="tab" :aria-selected="mode === 't2v'" :class="{ on: mode === 't2v' }" @click="mode = 't2v'">文生视频</button>
      <button type="button" role="tab" :aria-selected="mode === 'i2v'" :class="{ on: mode === 'i2v' }" @click="mode = 'i2v'">图生视频</button>
      <button type="button" role="tab" :aria-selected="mode === 'r2v'" :class="{ on: mode === 'r2v' }" @click="mode = 'r2v'">参考图</button>
    </div>

    <div v-if="mode === 'r2v'" class="field">
      <span class="field-label">参考图<span class="aside">人物、物体、场景都可以，第 N 张就是 &lt;Subject N&gt;</span></span>
      <RefImages v-model="refs" :max="maxRefs || 6" />
    </div>

    <div v-if="mode === 'i2v'" class="field">
      <span class="field-label">关键帧<span class="aside">尾帧可选，给了就在两张图之间过渡</span></span>
      <div class="keyframes">
        <div class="keyframe">
          <span class="kf-label">首帧</span>
          <ImageDrop v-model="imageFile" label="首帧" placeholder="拖入或点击选择" @size="imageSize = $event" />
        </div>
        <div class="keyframe">
          <span class="kf-label">尾帧<span class="muted">（可选）</span></span>
          <ImageDrop v-model="lastFile" label="尾帧" placeholder="拖入或点击选择" />
        </div>
      </div>
      <p v-if="lastFile && !imageFile" class="help warn">尾帧需要配合首帧一起用。</p>
    </div>

    <div class="field">
      <div class="field-label">
        <span>提示词</span>
        <button type="button" class="btn quiet small" @click="toggleRaw">
          <component :is="rawMode ? PhRows : PhTextAlignLeft" :size="14" />
          {{ rawMode ? '分段编辑' : '原始提示词' }}
        </button>
      </div>

      <textarea
        v-if="rawMode"
        v-model="raw"
        class="textarea mono raw"
        rows="12"
        spellcheck="false"
        aria-label="原始提示词"
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
      <p v-if="mode === 'i2v'" class="help">首帧对应 &lt;Picture 1&gt;，尾帧对应 &lt;Picture 2&gt;。没写的话服务端会自动加上引用。</p>
      <p v-if="mode === 'r2v' && !rawMode" class="help">主体定义、摘要和保留要求会按参考图自动生成，切到原始提示词可以看到完整内容。</p>
    </div>

    <div class="field">
      <span class="field-label">清晰度</span>
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
      <span class="field-label">LoRA<span class="aside">底模按生成方式自动切换</span></span>
      <div class="loras" role="radiogroup" aria-label="LoRA">
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
          <span class="lora-name">{{ l.label }}<span v-if="l.id === recommended" class="pill">推荐</span></span>
          <span class="lora-meta mono">{{ l.steps }} 步</span>
        </button>
      </div>
      <dl v-if="currentLora" class="models">
        <div><dt>底模</dt><dd class="mono" :title="currentLora.models.unet">{{ shortModel(currentLora.models.unet) }}</dd></div>
        <div><dt>LoRA</dt><dd class="mono" :title="currentLora.models.lora">{{ shortModel(currentLora.models.lora) }}</dd></div>
        <div>
          <dt>采样</dt>
          <dd class="mono">{{ currentLora.models.sampler }} · {{ currentLora.steps }} 步 · shift {{ currentLora.models.shift_video }}/{{ currentLora.models.shift_audio }}</dd>
        </div>
      </dl>
    </div>

    <div class="field">
      <span class="field-label">画面比例</span>
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
        >{{ a === 'image' ? '跟随图片' : a }}</button>
      </div>
    </div>

    <div class="field">
      <label for="duration" class="field-label">
        <span>时长</span>
        <span class="aside mono">{{ frames }} 帧 / {{ timecode }}</span>
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

    <div class="field">
      <label for="seed" class="field-label">种子<span class="aside">留空则随机</span></label>
      <div class="seed">
        <input id="seed" v-model="seed" class="input mono" type="text" inputmode="numeric" placeholder="随机" />
        <button type="button" class="btn icon" aria-label="生成随机种子" @click="randomSeed">
          <PhShuffle :size="16" />
        </button>
      </div>
    </div>

    <div class="submit">
      <span class="estimate">
        <span v-if="outputSize" class="mono">{{ outputSize[0] }}×{{ outputSize[1] }}</span>
        <span class="muted">预计约 {{ estimate }} 秒</span>
      </span>
      <button class="btn primary go" :disabled="!canSubmit">{{ submitting ? '提交中' : '生成视频' }}</button>
    </div>
    <p v-if="!ready" class="help">服务器还没准备好，模型加载完成后才能提交。</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
  </form>
</template>

<style scoped>
.form { display: flex; flex-direction: column; gap: 22px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.small { padding: 3px 10px; font-size: 12px; }

.modes {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; padding: 4px;
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
