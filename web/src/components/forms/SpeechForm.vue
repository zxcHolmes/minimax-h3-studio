<script setup>
import { computed, ref, toRefs } from 'vue'
import { useDraft, useJobSubmission, fileFrom } from '../../composables/useGeneration'
import AudioUpload from '../AudioUpload.vue'
import FormFooter from './FormFooter.vue'
const props = defineProps({ speech: Object, audioModel: String, ready: Boolean })
const emit = defineEmits(['created'])
const choice = computed(() => props.speech?.models?.find((m) => m.id === props.audioModel))
const draft = useDraft(`speech.${props.audioModel}`, { text: '', speechMode: 'generate', instruction: '', language: 'auto', voice: 'Vivian', referenceText: '', omniAttributes: {} })
const { text, speechMode, instruction, language, voice, referenceText, omniAttributes } = toRefs(draft)
const reference = ref(null)
const { seed, submitting, error, send } = useJobSubmission(emit)
const modes = { generate: 'Generate', clone: 'Clone voice', design: 'Voice design' }
const effectiveInstruction = computed(() => props.audioModel === 'qwen3_tts' && speechMode.value === 'clone' ? '' : props.audioModel === 'omnivoice' ? Object.values(omniAttributes.value).filter(Boolean).join(', ') : instruction.value)
const canSubmit = computed(() => props.ready && !submitting.value && text.value.trim() && (speechMode.value !== 'clone' || reference.value) && (speechMode.value !== 'design' || effectiveInstruction.value.trim()))
function submit() {
  if (!canSubmit.value) return
  const body = new FormData()
  Object.entries({ kind: 'speech', audio_model: props.audioModel, prompt: text.value, speech_mode: speechMode.value, instruction: effectiveInstruction.value, language: language.value, voice: voice.value, reference_text: referenceText.value }).forEach(([k, v]) => body.append(k, v))
  if (speechMode.value === 'clone') body.append('voice_audio', reference.value)
  return send(body)
}
async function reuse(job) {
  const o = job.audio_options || {}
  text.value = job.prompt; speechMode.value = o.speech_mode || 'generate'; instruction.value = o.instruction || ''; language.value = o.language || 'auto'; voice.value = o.voice || 'Vivian'; referenceText.value = o.reference_text || ''; seed.value = String(job.seed)
  if (props.audioModel === 'omnivoice') { const parts = (o.instruction || '').split(',').map((s) => s.trim()); omniAttributes.value = Object.fromEntries((props.speech?.instruction_groups || []).map((g) => [g.id, g.values.find((v) => parts.includes(v)) || undefined])) }
  try { reference.value = job.input_media_url ? await fileFrom(job.input_media_url, job.input_media) : null } catch (e) { error.value = e.message }
}
async function useAsVoice(job) {
  try { reference.value = await fileFrom(job.audio_url, job.audio); speechMode.value = 'clone'; referenceText.value = job.prompt; text.value = ''; error.value = '' } catch (e) { error.value = e.message }
}
defineExpose({ reuse, useAsVoice })
</script>
<template>
  <form class="generation-form" @submit.prevent="submit">
    <div class="field"><span class="field-label">Task</span><div class="chips"><button v-for="m in choice?.modes || []" :key="m" type="button" class="chip" :class="{ on: speechMode === m }" :aria-pressed="speechMode === m" @click="speechMode = m">{{ modes[m] }}</button></div></div>
    <div v-if="speechMode === 'clone'" class="field">
      <span class="field-label">Voice reference<span class="aside">Up to 30 seconds</span></span>
      <AudioUpload v-model="reference" label="Voice reference file" />
      <label for="voice-reference-text" class="field-label">Reference transcript<span class="aside">Optional</span></label>
      <textarea id="voice-reference-text" v-model="referenceText" class="textarea" rows="3" placeholder="The exact words spoken in the reference recording" />
      <p class="help">Use one clear speaker with little background noise.<template v-if="audioModel === 'qwen3_tts'"> Without a transcript, Qwen uses the speaker embedding only.</template></p>
    </div>
    <div v-if="audioModel !== 'qwen3_tts' || speechMode !== 'clone'" class="field">
      <label for="speech-instruction" class="field-label">{{ speechMode === 'design' ? 'Describe the voice' : 'Delivery / style' }}<span v-if="speechMode !== 'design'" class="aside">Optional</span></label>
      <div v-if="audioModel === 'omnivoice'" class="voice-attributes"><label v-for="group in speech?.instruction_groups || []" :key="group.id" class="field-label">{{ group.label }}<select v-model="omniAttributes[group.id]" class="input"><option :value="undefined">Auto</option><option v-for="v in group.values" :key="v" :value="v">{{ v }}</option></select></label></div>
      <textarea v-else id="speech-instruction" v-model="instruction" class="textarea" rows="3" placeholder="A warm adult female voice, clear Mandarin, gentle and unhurried, with a natural smile." />
      <p v-if="audioModel === 'voxcpm2'" class="help">Voice descriptions are applied using VoxCPM2’s native style prompt.</p>
    </div>
    <div v-if="speechMode === 'generate' && choice?.voices?.length" class="field"><label for="speech-voice" class="field-label">Voice preset</label><select id="speech-voice" v-model="voice" class="input"><option v-for="v in choice.voices" :key="v" :value="v">{{ v }}</option></select></div>
    <div class="field"><label for="speech-text" class="field-label">Text to speak<span class="aside mono">{{ text.length }}/4000</span></label><textarea id="speech-text" v-model="text" class="textarea" rows="8" maxlength="4000" placeholder="A gentle spring breeze carries cherry blossoms through the air. Wishing you a wonderful day." /></div>
    <div v-if="choice?.language" class="field"><label for="speech-language" class="field-label">Language</label><template v-if="audioModel === 'omnivoice'"><input id="speech-language" v-model="language" class="input" list="speech-languages" placeholder="auto, ISO code or language name" /><datalist id="speech-languages"><option v-for="(label, id) in speech?.languages" :key="id" :value="id">{{ label }}</option></datalist></template><select v-else id="speech-language" v-model="language" class="input"><option v-for="(label, id) in speech?.languages" :key="id" :value="id">{{ label }}</option></select></div>
    <p class="help">{{ choice?.label }} · audio.cpp · CUDA · WAV output</p>
    <FormFooter v-model:seed="seed" :ready="ready" :submitting="submitting" :can-submit="!!canSubmit" :error="error" :label="speechMode === 'clone' ? 'Generate cloned speech' : speechMode === 'design' ? 'Generate designed voice' : 'Generate speech'"><span>{{ modes[speechMode] }}</span><span class="muted">Native CUDA runtime</span></FormFooter>
  </form>
</template>

<style scoped>
.voice-attributes { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.voice-attributes label { flex-direction: column; align-items: stretch; gap: 6px; font-size: 12px; }
.voice-attributes select { width: 100%; }
</style>
