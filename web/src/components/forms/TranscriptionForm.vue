<script setup>
import { computed, ref, toRefs, watch } from 'vue'
import { useDraft, useJobSubmission, fileFrom } from '../../composables/useGeneration'
import AudioUpload from '../AudioUpload.vue'
import FormFooter from './FormFooter.vue'
const props = defineProps({ asr: Object, audioModel: String, ready: Boolean })
const emit = defineEmits(['created'])
const choice = computed(() => props.asr?.models?.find((m) => m.id === props.audioModel))
const draft = useDraft(`asr.${props.audioModel}`, { language: 'auto', timestamps: 'word' })
const { language, timestamps } = toRefs(draft)
const media = ref(null)
const { seed, submitting, error, send } = useJobSubmission(emit)
const labels = { none: 'Text only', word: 'Aligned words', segment: 'Subtitle segments' }
const canSubmit = computed(() => props.ready && !submitting.value && media.value)
watch(choice, (c) => { if (c && !c.timestamps.includes(timestamps.value)) timestamps.value = c.timestamps[0] })
function submit() {
  if (!canSubmit.value) return
  const body = new FormData()
  Object.entries({ kind: 'asr', audio_model: props.audioModel, language: language.value, timestamps: timestamps.value }).forEach(([k, v]) => body.append(k, v))
  body.append('media', media.value)
  return send(body)
}
async function reuse(job) {
  language.value = job.audio_options?.language || 'auto'; timestamps.value = job.audio_options?.timestamps || 'none'
  try { media.value = await fileFrom(job.input_media_url, job.input_media) } catch (e) { error.value = e.message }
}
defineExpose({ reuse })
</script>
<template>
  <form class="generation-form" @submit.prevent="submit">
    <div class="field"><span class="field-label">Audio or video</span><AudioUpload v-model="media" video label="Transcription media file" /><p class="help">WAV, MP3, M4A, FLAC, MP4, MOV, WebM and other readable recordings. Up to 2 hours / 256 MB. Video audio is extracted automatically.</p></div>
    <div class="field"><label for="asr-language" class="field-label">Language hint</label><input id="asr-language" v-model="language" class="input" list="asr-languages" placeholder="auto, ISO code or language name" /><datalist id="asr-languages"><option v-for="(label, id) in asr?.languages" :key="id" :value="id">{{ label }}</option></datalist></div>
    <div class="field"><span class="field-label">Timing</span><div class="chips"><button v-for="t in choice?.timestamps || []" :key="t" type="button" class="chip" :class="{ on: timestamps === t }" :aria-pressed="timestamps === t" @click="timestamps = t">{{ labels[t] }}</button></div>
      <p class="help">Word timing uses Qwen3 Forced Aligner. Subtitle cues are grouped from those aligned words; TXT, JSON, word JSON, SRT and VTT are available.</p>
    </div>
    <p class="help">{{ choice?.label }} · audio.cpp · CUDA</p>
    <FormFooter v-model:seed="seed" :seed-visible="false" :ready="ready" :submitting="submitting" :can-submit="!!canSubmit" :error="error" label="Transcribe"><span>{{ labels[timestamps] }}</span><span class="muted">Uploaded file</span></FormFooter>
  </form>
</template>
