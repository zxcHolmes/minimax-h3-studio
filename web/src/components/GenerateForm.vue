<script setup>
import { computed, nextTick, ref } from 'vue'
import { generationModes, imageMode } from '../generationModes'
import VideoForm from './forms/VideoForm.vue'
import PictureForm from './forms/PictureForm.vue'
import MusicForm from './forms/MusicForm.vue'
import MeshForm from './forms/MeshForm.vue'
import './forms/form.css'

const props = defineProps({
  resolutions: Array, groups: Array, loras: Array, defaultLoras: Object, aspects: Array, durationRange: Array,
  maxRefs: Number, maxRefVideos: Number, strengthRange: Array, samplers: Array,
  picture: Object, music: Object, mesh: Object, ready: Boolean,
})
const mode = defineModel('mode', { default: 't2v' })
const emit = defineEmits(['created'])
const forms = { video: VideoForm, picture: PictureForm, music: MusicForm, mesh: MeshForm }
const current = computed(() => generationModes.find((m) => m.id === mode.value) || generationModes[0])
const child = ref(null)
const familyProps = computed(() => {
  const { picture, music, mesh, ready, ...video } = props
  return current.value.family === 'video' ? { ...video, ready, mode: mode.value }
    : current.value.family === 'picture' ? { picture, aspects: props.aspects, ready, imageModel: current.value.imageModel }
      : current.value.family === 'music' ? { music, ready } : { mesh, ready }
})
async function route(targetMode, method, job) {
  mode.value = targetMode
  await nextTick()
  return child.value?.[method]?.(job)
}
function reuse(job) {
  const mode = ['t2i', 'i2i'].includes(job.mode) ? imageMode(job.image_model) : job.mode === 'fl2v' ? 'i2v' : job.mode
  return route(mode, 'reuse', job)
}
function useAsEdit(job) {
  const choice = current.value.imageModel
  return route(imageMode(choice && choice !== 'moss' ? choice : 'flux-klein-4b'), 'useAsEdit', job)
}
defineExpose({
  reuse,
  useAsEdit,
  useAsRef: (job) => route('r2v', 'useAsRef', job),
  useAsFrame: (job) => route('i2v', 'useAsFrame', job),
  useAsAudio: (job) => route('t2v', 'useAsAudio', job),
  useAs3D: (job) => route('i23d', 'useAs3D', job),
})
</script>
<template>
  <div class="form-heading">
    <h2>{{ current.label }}</h2><span class="mono">{{ current.model }}</span>
  </div>
  <KeepAlive>
    <component :is="forms[current.family]" :key="current.imageModel || current.family" ref="child" v-bind="familyProps" @update:mode="mode = $event" @created="emit('created', $event)" />
  </KeepAlive>
</template>
<style scoped>
.form-heading { padding-bottom: 18px; margin-bottom: 22px; border-bottom: 1px solid var(--line); }
h2 { margin: 0 0 4px; font-size: 19px; letter-spacing: -.025em; font-weight: 600; }
.form-heading span { font-size: 11px; color: var(--muted); }
</style>
