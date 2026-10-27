<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { PhUploadSimple, PhX } from '@phosphor-icons/vue'
const file = defineModel({ default: null })
const props = defineProps({ label: { type: String, default: 'Audio or video file' }, video: { type: Boolean, default: false } })
const url = ref('')
watch(file, (value) => { if (url.value) URL.revokeObjectURL(url.value); url.value = value ? URL.createObjectURL(value) : '' }, { immediate: true })
onBeforeUnmount(() => { if (url.value) URL.revokeObjectURL(url.value) })
function pick(files) { if (files?.[0]) file.value = files[0] }
</script>
<template>
  <div class="audio-upload" @dragover.prevent @drop.prevent="pick($event.dataTransfer.files)">
    <template v-if="file">
      <div class="file-row"><span class="mono" :title="file.name">{{ file.name }}</span><button type="button" class="btn icon small" :aria-label="`Remove ${label}`" @click="file = null"><PhX :size="14" /></button></div>
      <video v-if="file.type.startsWith('video/')" :src="url" controls preload="metadata" playsinline />
      <audio v-else :src="url" controls preload="metadata" />
    </template>
    <label v-else class="picker">
      <PhUploadSimple :size="23" /><span>Drop {{ video ? 'audio or video' : 'reference audio' }} here</span><small>or choose a file</small>
      <input type="file" :accept="video ? 'audio/*,video/*,.mkv' : 'audio/*,video/*'" :aria-label="label" @change="pick($event.target.files); $event.target.value = ''" />
    </label>
  </div>
</template>
<style scoped>
.audio-upload { border: 1px dashed var(--line); border-radius: var(--r-card); padding: 12px; background: var(--surface-sunk); min-width: 0; }
.picker { position: relative; min-height: 105px; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 6px; color: var(--text-2); cursor: pointer; font-size: 13px; }
.picker small { color: var(--muted); }
.picker input { position: absolute; inset: 0; width: 100%; opacity: 0; cursor: pointer; }
.file-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.file-row span { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
audio, video { display: block; width: 100%; max-height: 220px; }
</style>
