<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { PhFilmSlate } from '@phosphor-icons/vue'
import { api } from './api'
import GenerateForm from './components/GenerateForm.vue'
import JobCard from './components/JobCard.vue'
import Logo from './components/Logo.vue'

const health = ref(null)
const resolutions = ref([])
const loras = ref([])
const defaultLoras = ref({})
const aspects = ref([])
const durationRange = ref([2, 15])
const maxRefs = ref(6)
const jobs = ref(null)
const offline = ref(false)
const form = ref(null)
const now = ref(Date.now())
let timer = null
let clock = null

const ready = computed(() => health.value?.state === 'ready')
const active = computed(() => (jobs.value || []).some((j) => j.status === 'queued' || j.status === 'running'))

const status = computed(() => {
  if (offline.value) return { text: '连不上服务器', tone: 'bad' }
  const h = health.value
  if (!h) return { text: '正在连接', tone: '' }
  if (h.state === 'loading') return { text: '正在加载模型', tone: 'busy' }
  if (h.state === 'error') return { text: '模型加载失败', tone: 'bad' }
  if (h.running) return { text: h.queued ? `正在生成，还有 ${h.queued} 个排队` : '正在生成', tone: 'busy' }
  return { text: h.family === 'ref2va' ? '空闲 · 参考图模型' : '空闲', tone: 'idle' }
})

async function refresh() {
  try {
    const [h, j] = await Promise.all([api.health(), api.jobs()])
    health.value = h
    jobs.value = j
    offline.value = false
  } catch {
    offline.value = true
  }
  clearTimeout(timer)
  timer = setTimeout(refresh, active.value || !ready.value ? 1500 : 8000)
}

async function cancel(job) {
  await api.cancel(job.id)
  refresh()
}

async function remove(job) {
  if (!confirm('删除这条记录和它的视频文件？')) return
  await api.remove(job.id)
  refresh()
}

function reuse(job) {
  form.value?.reuse(job)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

onMounted(async () => {
  try {
    const p = await api.presets()
    resolutions.value = p.resolutions
    loras.value = p.loras
    defaultLoras.value = p.default_loras
    aspects.value = p.aspect_ratios
    durationRange.value = p.duration_range
    maxRefs.value = p.max_refs || 6
  } catch { /* refresh() reports offline */ }
  refresh()
  clock = setInterval(() => { now.value = Date.now() }, 1000)
})
onUnmounted(() => { clearTimeout(timer); clearInterval(clock) })
</script>

<template>
  <header class="top">
    <div class="brand">
      <Logo :size="24" :live="!!health?.running" />
      <span>H3 Turbo Studio</span>
    </div>
    <span class="status" :class="status.tone" role="status"><i v-if="status.tone" />{{ status.text }}</span>
  </header>

  <main class="layout">
    <aside class="composer">
      <GenerateForm
        ref="form"
        :resolutions="resolutions"
        :loras="loras"
        :default-loras="defaultLoras"
        :aspects="aspects"
        :duration-range="durationRange"
        :max-refs="maxRefs"
        :ready="ready"
        @created="refresh"
      />
      <details v-if="health?.load_error" class="load-error">
        <summary>模型加载错误</summary>
        <pre>{{ health.load_error }}</pre>
      </details>
    </aside>

    <section class="dailies" aria-label="生成记录">
      <h1 class="title">Dailies<span v-if="jobs?.length" class="count mono">{{ jobs.length }}</span></h1>

      <div v-if="jobs === null" class="grid">
        <div v-for="n in 4" :key="n" class="skeleton" />
      </div>
      <div v-else-if="!jobs.length" class="empty">
        <PhFilmSlate :size="34" weight="duotone" />
        <p>还没有视频。写好画面描述，点“生成视频”，结果会出现在这里。</p>
      </div>
      <div v-else class="grid">
        <JobCard
          v-for="job in jobs"
          :key="job.id"
          :job="job"
          :now="now"
          @cancel="cancel"
          @remove="remove"
          @reuse="reuse"
        />
      </div>
    </section>
  </main>
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
  display: grid; grid-template-columns: minmax(380px, 440px) 1fr; gap: 32px;
  max-width: 1600px; margin: 0 auto; padding: 28px; align-items: start;
}
.composer {
  background: var(--surface); border-radius: var(--r-card); box-shadow: var(--shadow); padding: 20px;
  position: sticky; top: 84px; max-height: calc(100dvh - 108px); overflow: auto;
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
.load-error { margin-top: 16px; }
.load-error summary { color: var(--live); cursor: pointer; font-size: 12.5px; }
.load-error pre { white-space: pre-wrap; font-size: 11px; color: var(--live); }

@media (max-width: 960px) {
  .top { padding: 0 16px; }
  .layout { grid-template-columns: 1fr; padding: 16px; gap: 24px; }
  .composer { position: static; max-height: none; }
  .grid { grid-template-columns: 1fr; }
}
</style>
