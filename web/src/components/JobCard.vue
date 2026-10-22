<script setup>
import { computed } from 'vue'
import { shortModel } from '../models'
import { PhArrowCounterClockwise, PhDownloadSimple, PhImage, PhStop, PhTrash, PhWarningCircle } from '@phosphor-icons/vue'

const props = defineProps({ job: Object, now: Number })
const emit = defineEmits(['cancel', 'remove', 'reuse'])

const STAGES = { loading: '切换模型', encoding: '理解提示词', sampling: '生成画面和声音', decoding: '解码视频', saving: '写入文件' }
const MODES = { t2v: '文生', i2v: '首帧', fl2v: '首尾帧', r2v: '参考图' }

// Sampling dominates the run time, so it gets most of the bar.
const SPANS = { loading: [0, 0], encoding: [0, 0.05], sampling: [0.05, 0.86], decoding: [0.86, 0.98], saving: [0.98, 1] }
const overall = computed(() => {
  const span = SPANS[props.job.stage]
  return span ? span[0] + (span[1] - span[0]) * (props.job.progress || 0) : 0
})

const elapsed = computed(() => {
  const j = props.job
  if (!j.started_at) return null
  return Math.max(0, Math.round((j.finished_at || props.now / 1000) - j.started_at))
})

const frames = computed(() => props.job.result?.frames)
const clipLength = computed(() => (frames.value ? (frames.value / 24).toFixed(1) : props.job.duration))
const created = computed(() => new Date(props.job.created_at * 1000).toLocaleString('zh-CN', {
  month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
}))

// Show the picture section only; the labels are the same on every job.
const scene = computed(() => {
  const m = props.job.prompt.match(/(?:integrated_multimodal_description|detailed_description):\s*([\s\S]*?)(\n\s*\n\s*overall_soundscape:|$)/)
  return (m ? m[1] : props.job.prompt).trim()
})
</script>

<template>
  <article class="card" :class="job.status">
    <div class="screen" :style="{ aspectRatio: `${job.width} / ${job.height}` }">
      <video
        v-if="job.status === 'done' && job.video_url"
        :src="job.video_url"
        :poster="job.thumb_url"
        controls
        preload="none"
        playsinline
      />
      <template v-else>
        <img v-if="job.image_url || job.ref_urls?.length" class="ghost" :src="job.image_url || job.ref_urls[0]" alt="" />
        <div class="state">
          <template v-if="job.status === 'running'">
            <span class="rec"><i />REC</span>
            <span class="stage">{{ STAGES[job.stage] || job.stage }}</span>
            <span class="track"><span :style="{ transform: `scaleX(${overall})` }" /></span>
          </template>
          <span v-else-if="job.status === 'queued'" class="stage">排在第 {{ job.queue_position }} 位</span>
          <span v-else-if="job.status === 'failed'" class="stage failed"><PhWarningCircle :size="18" />生成失败</span>
          <span v-else class="stage muted">已取消</span>
        </div>
      </template>
    </div>

    <div class="body">
      <p class="scene" :title="scene">{{ scene }}</p>

      <dl class="specs mono">
        <div><dt>模式</dt><dd>{{ MODES[job.mode] || job.mode }}<template v-if="job.mode === 'r2v'"> ×{{ job.refs.length }}</template><PhImage v-else-if="job.image" :size="12" /></dd></div>
        <div><dt>尺寸</dt><dd>{{ job.width }}×{{ job.height }}</dd></div>
        <div><dt>时长</dt><dd>{{ clipLength }}s</dd></div>
        <div><dt>耗时</dt><dd>{{ elapsed === null ? '-' : `${elapsed}s` }}</dd></div>
      </dl>

      <p v-if="job.models" class="models mono" :title="`${job.models.unet}\n${job.models.lora}`">
        {{ shortModel(job.models.unet) }} + {{ shortModel(job.models.lora) }}
      </p>

      <details v-if="job.status === 'failed' && job.error" class="error">
        <summary>查看错误</summary>
        <pre>{{ job.error }}</pre>
      </details>

      <footer class="foot">
        <span class="meta mono" :title="`seed ${job.seed}`">{{ job.preset }} · {{ created }}</span>
        <div class="actions">
          <button v-if="job.status === 'queued' || job.status === 'running'" class="btn danger small" @click="emit('cancel', job)">
            <PhStop :size="13" weight="fill" />取消
          </button>
          <template v-else>
            <a v-if="job.video_url" class="btn small" :href="job.video_url" :download="`h3_${job.id}.mp4`">
              <PhDownloadSimple :size="14" />下载
            </a>
            <button class="btn small" @click="emit('reuse', job)"><PhArrowCounterClockwise :size="14" />复用</button>
            <button class="btn icon small danger" aria-label="删除" @click="emit('remove', job)"><PhTrash :size="14" /></button>
          </template>
        </div>
      </footer>
    </div>
  </article>
</template>

<style scoped>
.card {
  background: var(--surface); border-radius: var(--r-card); box-shadow: var(--shadow);
  overflow: hidden; display: flex; flex-direction: column;
}
.screen { position: relative; background: var(--screen); max-height: 420px; width: 100%; }
.screen video { width: 100%; height: 100%; display: block; object-fit: contain; background: var(--screen); }
.ghost { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: .28; filter: blur(1px); }
.state {
  position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 10px; color: #dfe1e6; padding: 16px;
}
.stage { font-size: 13px; display: inline-flex; align-items: center; gap: 6px; }
.stage.failed { color: #ff8d90; }
.rec {
  position: absolute; top: 12px; left: 12px; display: inline-flex; align-items: center; gap: 6px;
  font: 600 11px/1 var(--font-mono); letter-spacing: .08em; color: #f2f3f5;
}
.rec i { width: 8px; height: 8px; border-radius: 50%; background: var(--live); animation: tally 1.4s ease-in-out infinite; }
@keyframes tally { 50% { opacity: .25; } }
.track { width: min(70%, 320px); height: 3px; border-radius: 3px; background: rgba(255, 255, 255, .14); overflow: hidden; }
.track span { display: block; height: 100%; background: var(--accent); transform-origin: left; transition: transform .5s ease; }

.body { padding: 14px 16px 12px; display: flex; flex-direction: column; gap: 12px; flex: 1; }
.scene {
  margin: 0; font-size: 13px; line-height: 1.5; color: var(--text);
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
}
.specs { display: grid; grid-template-columns: repeat(4, auto); justify-content: start; gap: 4px 18px; margin: 0; }
.specs div { display: flex; flex-direction: column; }
.specs dt { font-size: 10.5px; color: var(--muted); font-family: var(--font); }
.specs dd { margin: 0; font-size: 12px; display: inline-flex; align-items: center; gap: 4px; }
.models {
  margin: -4px 0 0; font-size: 11px; color: var(--muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.error summary { cursor: pointer; color: var(--live); font-size: 12px; }
.error pre { white-space: pre-wrap; font-size: 11px; color: var(--live); max-height: 200px; overflow: auto; margin: 6px 0 0; }
.foot { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-top: auto; }
.meta { font-size: 11px; color: var(--muted); }
.actions { display: flex; gap: 6px; }
.small { padding: 4px 11px; font-size: 12px; }
.icon.small { padding: 5px; }
</style>
