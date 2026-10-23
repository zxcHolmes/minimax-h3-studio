<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { shortModel } from '../models'
import { PhArrowCounterClockwise, PhArrowsOut, PhDownloadSimple, PhFilmStrip, PhImage, PhMusicNotes, PhSpeakerHigh, PhStop, PhTrash, PhUserFocus, PhWarningCircle } from '@phosphor-icons/vue'

const props = defineProps({ job: Object, now: Number, upscaleTargets: Array })
const emit = defineEmits(['cancel', 'remove', 'reuse', 'use-ref', 'use-frame', 'use-audio', 'upscale'])

const STAGES = { loading: 'Loading model', composing: 'Writing the song', encoding: 'Reading the prompt', sampling: 'Generating picture and sound', decoding: 'Decoding video', saving: 'Saving file', reading: 'Reading the video', upscaling: 'Upscaling' }
const MODES = { t2v: 'Text', i2v: 'First frame', fl2v: 'First + last', r2v: 'Reference', t2i: 'Picture', t2m: 'Music', upscale: 'Upscale' }

// Sampling dominates the run time, so it gets most of the bar.
const SPANS = { loading: [0, 0], encoding: [0, 0.05], sampling: [0.05, 0.86], decoding: [0.86, 0.98], saving: [0.98, 1] }
// Pictures: decoding a single image is instant, so sampling gets nearly all of the bar.
const PICTURE_SPANS = { loading: [0, 0], encoding: [0, 0.1], sampling: [0.1, 0.97], decoding: [0.97, 0.99], saving: [0.99, 1] }
// Music: the text encoder writes the acoustic tokens first, which takes most of the time.
const MUSIC_SPANS = { loading: [0, 0], composing: [0, 0.72], sampling: [0.72, 0.96], decoding: [0.96, 0.99], saving: [0.99, 1] }
// Upscaling: one SeedVR2 step per temporal chunk; the tiled VAE encode and decode take about as long.
const UPSCALE_SPANS = { loading: [0, 0], reading: [0, 0.2], upscaling: [0.2, 0.6], decoding: [0.6, 0.97], saving: [0.97, 1] }
const isPicture = computed(() => props.job.mode === 't2i')
const isMusic = computed(() => props.job.mode === 't2m')
const isUpscale = computed(() => props.job.mode === 'upscale')
const overall = computed(() => {
  const spans = isPicture.value ? PICTURE_SPANS : isMusic.value ? MUSIC_SPANS : isUpscale.value ? UPSCALE_SPANS : SPANS
  const span = spans[props.job.stage]
  return span ? span[0] + (span[1] - span[0]) * (props.job.progress || 0) : 0
})

const elapsed = computed(() => {
  const j = props.job
  if (!j.started_at) return null
  return Math.max(0, Math.round((j.finished_at || props.now / 1000) - j.started_at))
})

const frames = computed(() => props.job.result?.frames)
const clipLength = computed(() => {
  if (isMusic.value) {
    const s = Math.round(props.job.result?.seconds ?? props.job.duration)
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
  }
  return `${frames.value ? (frames.value / 24).toFixed(1) : props.job.duration}s`
})
// Targets above the video's short side ('1080p' -> 1080); picking one queues a SeedVR2 upscale.
const targets = computed(() => props.job.video_url
  ? (props.upscaleTargets || []).filter((t) => parseInt(t) > Math.min(props.job.width, props.job.height))
  : [])
const choosing = ref(false)
function upscale(target) {
  choosing.value = false
  emit('upscale', props.job, target)
}

const created = computed(() => new Date(props.job.created_at * 1000).toLocaleString('en-US', {
  month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
}))

// Show the picture section only; the labels are the same on every job.
const scene = computed(() => {
  const m = props.job.prompt.match(/(?:integrated_multimodal_description|detailed_description):\s*([\s\S]*?)(\n\s*\n\s*overall_soundscape:|$)/)
  return (m ? m[1] : props.job.prompt).trim()
})

// The prompt is clamped to three lines; offer a toggle only when it actually overflows.
const sceneEl = ref(null)
const expanded = ref(false)
const clamped = ref(false)
let observer
function measure() {
  const el = sceneEl.value
  if (el && !expanded.value) clamped.value = el.scrollHeight > el.clientHeight + 1
}
onMounted(() => {
  measure()
  observer = new ResizeObserver(measure)
  observer.observe(sceneEl.value)
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <article class="card" :class="job.status">
    <div class="screen" :class="{ music: isMusic }" :style="{ aspectRatio: isMusic ? '16 / 6' : `${job.width} / ${job.height}` }">
      <div v-if="isMusic && job.status === 'done' && job.audio_url" class="player">
        <PhMusicNotes :size="34" weight="duotone" />
        <audio :src="job.audio_url" controls preload="none" />
      </div>
      <a v-else-if="job.status === 'done' && job.picture_url" :href="job.picture_url" target="_blank" rel="noopener">
        <img class="picture" :src="job.picture_url" :alt="job.prompt" loading="lazy" />
      </a>
      <video
        v-else-if="job.status === 'done' && job.video_url"
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
          <span v-else-if="job.status === 'queued'" class="stage">Queued, #{{ job.queue_position }}</span>
          <span v-else-if="job.status === 'failed'" class="stage failed"><PhWarningCircle :size="18" />Generation failed</span>
          <span v-else class="stage muted">Canceled</span>
        </div>
      </template>
    </div>

    <div class="body">
      <div class="prompt">
        <p ref="sceneEl" class="scene" :class="{ open: expanded }">{{ scene }}</p>
        <button v-if="clamped || expanded" class="more" @click="expanded = !expanded">
          {{ expanded ? 'Show less' : 'Show more' }}
        </button>
      </div>

      <details v-if="job.lyrics" class="lyrics">
        <summary>Lyrics</summary>
        <pre>{{ job.lyrics }}</pre>
      </details>

      <dl class="specs mono">
        <div><dt>Mode</dt><dd>{{ MODES[job.mode] || job.mode }}<template v-if="job.mode === 'r2v'"> ×{{ job.refs.length }}</template><PhImage v-else-if="job.image" :size="12" /><PhSpeakerHigh v-if="job.guide_audio" :size="12" :title="`Guide audio from ${job.audio_start || 0} s`" /></dd></div>
        <div v-if="!isMusic"><dt>Size</dt><dd>{{ job.width }}×{{ job.height }}</dd></div>
        <div v-if="!isPicture"><dt>Length</dt><dd>{{ clipLength }}</dd></div>
        <div><dt>Time</dt><dd>{{ elapsed === null ? '-' : `${elapsed}s` }}</dd></div>
      </dl>

      <p v-if="job.models" class="models mono" :title="[job.models.unet, job.models.lora].filter(Boolean).join('\n')">
        {{ shortModel(job.models.unet) }}<template v-if="job.models.lora"> + {{ shortModel(job.models.lora) }}<template v-if="(job.models.lora_strength ?? 1) !== 1"> ×{{ job.models.lora_strength }}</template></template><template v-if="job.sampler"> · {{ job.models.sampler }}</template><template v-if="job.steps"> · {{ job.models.steps }} steps</template>
      </p>

      <details v-if="job.status === 'failed' && job.error" class="error">
        <summary>Show error</summary>
        <pre>{{ job.error }}</pre>
      </details>

      <footer class="foot">
        <span class="meta mono" :title="`seed ${job.seed}`">{{ [job.preset, created].filter(Boolean).join(' · ') }}</span>
        <div class="actions">
          <button v-if="job.status === 'queued' || job.status === 'running'" class="btn danger small" @click="emit('cancel', job)">
            <PhStop :size="13" weight="fill" />Cancel
          </button>
          <template v-else>
            <a v-if="job.video_url" class="btn small" :href="job.video_url" :download="`h3_${job.id}.mp4`">
              <PhDownloadSimple :size="14" />Download
            </a>
            <a v-if="job.audio_url" class="btn small" :href="job.audio_url" :download="`music_${job.id}.mp3`">
              <PhDownloadSimple :size="14" />Download
            </a>
            <button v-if="job.audio_url" class="btn small" title="Use as the guide audio of a video" @click="emit('use-audio', job)">
              <PhFilmStrip :size="14" />Video
            </button>
            <template v-if="job.picture_url">
              <a class="btn icon small" :href="job.picture_url" :download="`moss_${job.id}.png`" aria-label="Download" title="Download">
                <PhDownloadSimple :size="14" />
              </a>
              <button class="btn small" title="Use as a reference image" @click="emit('use-ref', job)"><PhUserFocus :size="14" />Reference</button>
              <button class="btn small" title="Use as the first frame" @click="emit('use-frame', job)"><PhFilmStrip :size="14" />Frame</button>
            </template>
            <template v-if="targets.length">
              <button v-if="!choosing" class="btn small" title="Upscale with SeedVR2" @click="choosing = true">
                <PhArrowsOut :size="14" />Upscale
              </button>
              <button v-for="t in targets" v-else :key="t" class="btn small" @click="upscale(t)">{{ t }}</button>
            </template>
            <button v-if="!isUpscale" class="btn small" @click="emit('reuse', job)"><PhArrowCounterClockwise :size="14" />Reuse</button>
            <button class="btn icon small danger" aria-label="Delete" @click="emit('remove', job)"><PhTrash :size="14" /></button>
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
.screen video, .picture { width: 100%; height: 100%; display: block; object-fit: contain; background: var(--screen); }
.screen > a { display: block; width: 100%; height: 100%; }
.player {
  position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 14px; padding: 16px; color: #dfe1e6;
}
.player audio { width: min(100%, 420px); }
.lyrics summary { cursor: pointer; color: var(--accent); font-size: 12px; }
.lyrics pre {
  margin: 6px 0 0; font: 12px/1.5 var(--font); color: var(--text-2); white-space: pre-wrap;
  max-height: 220px; overflow: auto;
}
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
  white-space: pre-line;
}
.scene.open { display: block; -webkit-line-clamp: unset; }
.more {
  margin-top: 2px; padding: 0; border: 0; background: none; cursor: pointer;
  font: inherit; font-size: 12px; color: var(--accent);
}
.more:hover { text-decoration: underline; }
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
.foot { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; margin-top: auto; }
.meta { font-size: 11px; color: var(--muted); white-space: nowrap; }
.actions { display: flex; gap: 6px; }
.small { padding: 4px 11px; font-size: 12px; }
.icon.small { padding: 5px; }
</style>
