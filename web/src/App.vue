<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { PhCaretLeft, PhCaretRight, PhFilmSlate } from '@phosphor-icons/vue'
import { api } from './api'
import ConfirmDialog from './components/ConfirmDialog.vue'
import GenerateForm from './components/GenerateForm.vue'
import JobCard from './components/JobCard.vue'
import ModeNav from './components/ModeNav.vue'
import { historyForMode, initialMode } from './generationModes'
import Logo from './components/Logo.vue'

const mode = ref(initialMode())
const history = computed(() => historyForMode(mode.value))
const composerScroll = ref(null)
watch(mode, async (value) => {
  try { localStorage.setItem('h3.mode', value) } catch { /* storage */ }
  await nextTick()
  // A shorter family must not inherit a long form's previous scroll offset.
  composerScroll.value?.scrollTo({ top: 0 })
  if (window.matchMedia('(max-width: 960px)').matches) window.scrollTo({ top: 0 })
})
const mesh = ref(null)
const health = ref(null)
const resolutions = ref([])
const groups = ref([])
const loras = ref([])
const defaultLoras = ref({})
const aspects = ref([])
const durationRange = ref([2, 15])
const maxRefs = ref(6)
const maxRefVideos = ref(3)
const strengthRange = ref([0, 2])
const samplers = ref([])
const picture = ref(null)
const music = ref(null)
const upscale = ref(null)
const PAGE_SIZE = 24
const jobs = ref(null)
const total = ref(0)
const page = ref(1)
const dailies = ref(null)
const offline = ref(false)
const form = ref(null)
const confirmer = ref(null)
const now = ref(Date.now())
let timer = null
let clock = null
let refreshVersion = 0

const ready = computed(() => health.value?.state === 'ready')
const active = computed(() => !!(health.value?.running || health.value?.queued)
  || (jobs.value || []).some((j) => j.status === 'queued' || j.status === 'running'))
const pages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
// Page buttons: first, last, and the neighbours of the current page; null marks a gap.
const pageList = computed(() => {
  const n = pages.value, cur = page.value
  const keep = [...new Set([1, n, cur - 1, cur, cur + 1])].filter((p) => p >= 1 && p <= n).sort((a, b) => a - b)
  return keep.flatMap((p, i) => (i && p - keep[i - 1] > 1 ? [null, p] : [p]))
})

const status = computed(() => {
  if (offline.value) return { text: 'Server unreachable', tone: 'bad' }
  const h = health.value
  if (!h) return { text: 'Connecting', tone: '' }
  if (h.state === 'loading') return { text: 'Loading models', tone: 'busy' }
  if (h.state === 'error') return { text: 'Models failed to load', tone: 'bad' }
  if (h.running) return { text: h.queued ? `Generating, ${h.queued} queued` : 'Generating', tone: 'busy' }
  if (!h.unet) return { text: h.loaded_models?.length ? `Idle · ${h.loaded_models.join(', ')}` : 'Idle · models unloaded', tone: 'idle' }
  return { text: h.family === 'ref2va' ? 'Idle · reference model' : 'Idle', tone: 'idle' }
})

async function refresh() {
  const version = ++refreshVersion
  clearTimeout(timer)
  try {
    const [h, j] = await Promise.all([api.health(), api.jobs(PAGE_SIZE, (page.value - 1) * PAGE_SIZE, history.value.kind, history.value.imageModel)])
    if (version !== refreshVersion) return
    health.value = h
    total.value = j.total
    offline.value = false
    // Deleting the last job of the last page leaves it empty: step back.
    if (!j.items.length && page.value > 1) {
      page.value = Math.max(1, Math.ceil(j.total / PAGE_SIZE))
      return refresh()
    }
    jobs.value = j.items
  } catch {
    if (version !== refreshVersion) return
    offline.value = true
  }
  clearTimeout(timer)
  timer = setTimeout(refresh, active.value || !ready.value ? 1500 : 8000)
}

watch(() => `${history.value.kind}:${history.value.imageModel || ""}`, () => {
  page.value = 1
  total.value = 0
  jobs.value = null
  refresh()
})

async function cancel(job) {
  await api.cancel(job.id)
  refresh()
}

const OUTPUT = { i23d: '3D model', t2i: 'picture', i2i: 'picture', t2m: 'song' }

async function remove(job) {
  const scene = job.prompt.match(/(?:integrated_multimodal_description|detailed_description):\s*([\s\S]*?)(\n\s*\n|$)/)
  const ok = await confirmer.value.ask({
    title: 'Delete this job?',
    detail: (scene ? scene[1] : job.prompt).replace(/^\s*\[Shot \d+\]\s*/, '').trim(),
    message: `The ${OUTPUT[job.mode] || 'video'} and its uploaded inputs are removed from the server. This cannot be undone.`,
    image: job.thumb_url,
    confirmLabel: 'Delete',
  })
  if (!ok) return
  await api.remove(job.id)
  refresh()
}

async function upscaleJob(job, upscaler, target) {
  await api.upscale(job.id, upscaler, target)
  created()
}

async function useEdit(job) {
  await form.value?.useAsEdit(job)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function use3D(job) {
  await form.value?.useAs3D(job)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function goTo(p) {
  if (p === page.value || p < 1 || p > pages.value) return
  page.value = p
  refresh()
  dailies.value?.scrollIntoView({ behavior: 'smooth' })
}

function created() {
  page.value = 1
  refresh()
}

function reuse(job) {
  form.value?.reuse(job)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function useRef(job) {
  await form.value?.useAsRef(job)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function useAudio(job) {
  await form.value?.useAsAudio(job)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function useFrame(job) {
  await form.value?.useAsFrame(job)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

onMounted(async () => {
  try {
    const p = await api.presets()
    resolutions.value = p.resolutions
    groups.value = p.groups || []
    loras.value = p.loras
    defaultLoras.value = p.default_loras
    aspects.value = p.aspect_ratios
    durationRange.value = p.duration_range
    maxRefs.value = p.max_refs || 6
    maxRefVideos.value = p.max_ref_videos || 3
    strengthRange.value = p.lora_strength_range || [0, 2]
    samplers.value = p.samplers || []
    picture.value = p.image || null
    mesh.value = p.mesh || null
    music.value = p.music || null
    upscale.value = p.upscale || null
  } catch { /* refresh() reports offline */ }
  refresh()
  clock = setInterval(() => { now.value = Date.now() }, 1000)
})
onUnmounted(() => { refreshVersion++; clearTimeout(timer); clearInterval(clock) })
</script>

<template>
  <header class="top">
    <div class="brand">
      <Logo :size="24" :live="!!health?.running" />
      <span>MiniMax-H3 Studio</span>
    </div>
    <span class="status" :class="status.tone" role="status"><i v-if="status.tone" />{{ status.text }}</span>
  </header>

  <main class="layout">
    <ModeNav v-model="mode" />
    <aside class="composer">
      <div ref="composerScroll" class="composer-scroll" tabindex="0" aria-label="Generation settings">
      <GenerateForm
        ref="form"
        v-model:mode="mode"
        :mesh="mesh"
        :resolutions="resolutions"
        :groups="groups"
        :loras="loras"
        :default-loras="defaultLoras"
        :aspects="aspects"
        :duration-range="durationRange"
        :max-refs="maxRefs"
        :max-ref-videos="maxRefVideos"
        :strength-range="strengthRange"
        :samplers="samplers"
        :picture="picture"
        :music="music"
        :ready="ready"
        @created="created"
      />
      <details v-if="health?.load_error" class="load-error">
        <summary>Model loading error</summary>
        <pre>{{ health.load_error }}</pre>
      </details>
      </div>
    </aside>

    <section ref="dailies" class="dailies" :aria-label="`${history.label} history`">
      <h1 class="title">{{ history.label }}<span v-if="total" class="count mono">{{ total }}</span></h1>

      <div v-if="jobs === null" class="grid">
        <div v-for="n in 4" :key="n" class="skeleton" />
      </div>
      <div v-else-if="!jobs.length" class="empty">
        <PhFilmSlate :size="34" weight="duotone" />
        <p>{{ history.empty }}</p>
      </div>
      <div v-else class="grid">
        <JobCard
          v-for="job in jobs"
          :key="job.id"
          :job="job"
          :now="now"
          :upscale="upscale"
          @cancel="cancel"
          @remove="remove"
          @reuse="reuse"
          @use-ref="useRef"
          @use-frame="useFrame"
          @use-audio="useAudio"
          @use-3d="use3D"
          @use-edit="useEdit"
          @upscale="upscaleJob"
        />
      </div>

      <nav v-if="pages > 1" class="pager mono" aria-label="Pages">
        <button class="btn icon small" :disabled="page === 1" aria-label="Previous page" @click="goTo(page - 1)">
          <PhCaretLeft :size="14" />
        </button>
        <template v-for="(p, i) in pageList" :key="p ?? `gap${i}`">
          <span v-if="p === null" class="gap">…</span>
          <button v-else class="btn small" :class="{ current: p === page }" :aria-current="p === page ? 'page' : null" @click="goTo(p)">
            {{ p }}
          </button>
        </template>
        <button class="btn icon small" :disabled="page === pages" aria-label="Next page" @click="goTo(page + 1)">
          <PhCaretRight :size="14" />
        </button>
      </nav>
    </section>
  </main>
  <ConfirmDialog ref="confirmer" />
</template>

<style scoped>
.top {
  height: 60px; display: flex; justify-content: space-between; align-items: center;
  padding: 0 28px; position: sticky; top: 0; z-index: 10;
  background: color-mix(in srgb, var(--bg) 86%, transparent); backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--line);
}
.brand { display: flex; align-items: center; gap: 9px; font-weight: 650; letter-spacing: -.01em; }
.status { display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--text-2); }
.status i { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); }
.status.idle i { background: var(--done); }
.status.busy i { background: var(--live); }
.status.bad { color: var(--live); }
.status.bad i { background: var(--live); }

.layout {
  display: grid; grid-template-columns: 176px minmax(340px, 400px) minmax(0, 1fr); gap: 24px;
  max-width: 1800px; margin: 0 auto; padding: 28px; align-items: start;
}
.composer {
  background: var(--surface); border-radius: var(--r-card); box-shadow: var(--shadow);
  position: sticky; top: 84px; height: calc(100dvh - 108px); min-width: 0; overflow: hidden;
  display: flex; flex-direction: column;
}
.composer-scroll {
  flex: 1 1 auto; min-height: 0; padding: 20px; overflow-y: auto; overflow-x: hidden;
  scrollbar-gutter: stable; overscroll-behavior-y: contain; overflow-anchor: none; touch-action: pan-y;
}
.title {
  margin: 4px 0 18px; font-size: 26px; font-weight: 650; letter-spacing: -.025em;
  display: flex; align-items: baseline; gap: 10px;
}
.count { font-size: 13px; font-weight: 500; color: var(--muted); letter-spacing: 0; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 20px; align-items: start; }
.skeleton {
  height: 330px; border-radius: var(--r-card); background: var(--surface);
  background-image: linear-gradient(100deg, transparent 30%, var(--surface-sunk) 50%, transparent 70%);
  background-size: 200% 100%; animation: shimmer 1.4s linear infinite;
}
@keyframes shimmer { to { background-position: -200% 0; } }
.empty {
  display: flex; flex-direction: column; align-items: center; gap: 10px; text-align: center;
  padding: 90px 24px; color: var(--muted); border: 1.5px dashed var(--line); border-radius: var(--r-card);
}
.empty p { margin: 0; max-width: 34ch; }
.pager { display: flex; justify-content: center; align-items: center; gap: 6px; margin: 28px 0 8px; }
.pager .small { padding: 4px 11px; font-size: 12px; min-width: 32px; justify-content: center; }
.pager .icon.small { padding: 5px 7px; }
.pager .current { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
.pager .gap { color: var(--muted); padding: 0 2px; }
.load-error { margin-top: 16px; }
.load-error summary { color: var(--live); cursor: pointer; font-size: 12.5px; }
.load-error pre { white-space: pre-wrap; font-size: 11px; color: var(--live); }

@media (max-width: 960px) {
  .top { padding: 0 16px; }
  .layout { grid-template-columns: 160px minmax(0, 1fr); padding: 16px; gap: 20px; }
  .mode-nav { grid-row: span 2; }
  .composer { position: static; height: auto; overflow: visible; }
  .composer-scroll { overflow: visible; scrollbar-gutter: auto; }
  .grid { grid-template-columns: 1fr; }
}
@media (max-width: 700px) {
  .layout { grid-template-columns: 44px minmax(0, 1fr); gap: 12px; padding: 12px; }
  .composer-scroll { padding: 16px; }
  .brand { font-size: 13px; }
  .status { font-size: 11px; }
}
</style>
