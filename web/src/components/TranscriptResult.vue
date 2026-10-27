<script setup>
import { computed } from 'vue'
const props = defineProps({ transcript: Object })
const cues = computed(() => props.transcript?.segments || [])
function clock(t) { return `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}.${String(Math.round(t % 1 * 1000)).padStart(3, '0')}` }
</script>
<template>
  <div class="transcript-result">
    <p class="transcript-text">{{ transcript?.text || 'No speech was recognized.' }}</p>
    <details v-if="cues.length"><summary>{{ cues.length }} timed segments<span v-if="transcript.segment_source === 'grouped_aligned_words'"> · grouped from aligned words</span></summary><div class="cues"><div v-for="(c, i) in cues" :key="i" class="cue"><span class="mono">{{ clock(c.start) }}–{{ clock(c.end) }}</span><p><b v-if="c.speaker !== undefined">Speaker {{ c.speaker }}: </b>{{ c.text }}</p></div></div></details>
    <p v-else class="timing-note">No timestamp spans returned. Text exports remain available.</p>
  </div>
</template>
<style scoped>
.transcript-result { padding: 20px; background: var(--surface); color: var(--text); }
.transcript-text { white-space: pre-wrap; font-size: 14px; line-height: 1.8; max-height: 280px; overflow-y: auto; margin: 0; }
summary, .timing-note { color: var(--muted); font-size: 11px; margin: 12px 0 0; }
summary { cursor: pointer; }
.cues { max-height: 260px; overflow-y: auto; padding-top: 10px; }
.cue { padding: 7px 0; border-top: 1px solid var(--line); }
.cue span { font-size: 10px; color: var(--muted); }
.cue p { margin: 3px 0 0; font-size: 12px; line-height: 1.6; }
</style>
