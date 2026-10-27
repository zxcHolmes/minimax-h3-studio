<script setup>
import { ref } from 'vue'
import { PhCube } from '@phosphor-icons/vue'
defineProps({ src: String, poster: String })
const opened = ref(false)
const loading = ref(false)
const error = ref('')
async function open() {
  loading.value = true
  error.value = ''
  try { await import('@google/model-viewer'); opened.value = true }
  catch { error.value = 'Could not load the 3D viewer. You can still download the GLB.'; loading.value = false }
}
</script>
<template>
  <div class="model-preview">
    <model-viewer v-if="opened" :src="src" alt="Generated 3D model. Drag to rotate; scroll to zoom." camera-controls touch-action="pan-y" shadow-intensity="1" @load="loading = false" @error="error = 'Unable to preview this model. Download the GLB to inspect it.'; loading = false" />
    <button v-else class="open-preview" :disabled="loading" @click="open">
      <img v-if="poster" :src="poster" alt="Source object" loading="lazy" />
      <span><PhCube :size="20" />{{ loading ? 'Loading viewer…' : 'Explore in 3D' }}</span>
    </button>
    <span v-if="opened && loading" class="hint">Loading model…</span>
    <span v-if="opened && !loading && !error" class="hint">Drag to rotate · Scroll to zoom</span>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
  </div>
</template>
<style scoped>
.model-preview { height: 100%; width: 100%; position: relative; background: #e9ebee; }
model-viewer { height: 100%; width: 100%; --poster-color: transparent; }
.open-preview { width: 100%; height: 100%; padding: 0; border: 0; cursor: pointer; background: transparent; display: grid; place-items: center; }
.open-preview img { position: absolute; width: 100%; height: 100%; object-fit: contain; }
.open-preview span { z-index: 1; display: flex; gap: 8px; align-items: center; border-radius: 999px; padding: 10px 18px; background: var(--surface); color: var(--text); box-shadow: var(--shadow); }
.hint { position: absolute; bottom: 10px; left: 50%; transform: translateX(-50%); font-size: 10px; color: #4b505b; pointer-events: none; white-space: nowrap; }
.error { position: absolute; inset: auto 12px 20px; color: #b0242d; background: #fbfbfc; font-size: 12px; padding: 8px; }
</style>
