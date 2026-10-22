<script setup>
import { onUnmounted, ref, watch } from 'vue'
import { PhImage, PhX } from '@phosphor-icons/vue'

// v-model is the File; `size` reports the picture's natural dimensions once known.
const file = defineModel({ type: [File, null], default: null })
const props = defineProps({ placeholder: String, label: String })
const emit = defineEmits(['size'])

const preview = ref(null)
const size = ref(null)
const dragging = ref(false)

watch(file, (f) => {
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = f ? URL.createObjectURL(f) : null
  size.value = null
  emit('size', null)
  if (!f) return
  const img = new Image()
  img.onload = () => {
    size.value = { w: img.naturalWidth, h: img.naturalHeight }
    emit('size', size.value)
  }
  img.src = preview.value
}, { immediate: true })

onUnmounted(() => { if (preview.value) URL.revokeObjectURL(preview.value) })

function pick(f) {
  if (f && f.type.startsWith('image/')) file.value = f
}
</script>

<template>
  <label
    class="drop"
    :class="{ dragging, filled: preview }"
    @dragover.prevent="dragging = true"
    @dragleave.prevent="dragging = false"
    @drop.prevent="dragging = false; pick($event.dataTransfer.files?.[0])"
  >
    <input type="file" accept="image/*" class="sr-only" :aria-label="props.label" @change="pick($event.target.files[0])" />
    <template v-if="preview">
      <img :src="preview" :alt="props.label" />
      <span v-if="size" class="size mono">{{ size.w }}×{{ size.h }}</span>
      <button type="button" class="btn icon remove" :aria-label="`Remove ${props.label}`" @click.prevent="file = null">
        <PhX :size="14" weight="bold" />
      </button>
    </template>
    <span v-else class="empty">
      <PhImage :size="24" weight="duotone" />
      <span>{{ props.placeholder }}</span>
    </span>
  </label>
</template>

<style scoped>
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.drop {
  position: relative; display: flex; align-items: center; justify-content: center;
  min-height: 132px; height: 100%; border: 1.5px dashed var(--line); border-radius: var(--r-card);
  background: var(--surface-sunk); cursor: pointer; overflow: hidden; transition: border-color .15s;
}
.drop:hover, .drop.dragging { border-color: var(--accent); }
.drop.filled { border-style: solid; background: var(--screen); }
.drop img { max-width: 100%; max-height: 200px; display: block; }
.empty {
  display: flex; flex-direction: column; align-items: center; gap: 6px;
  color: var(--muted); font-size: 12.5px; text-align: center; padding: 12px;
}
.size {
  position: absolute; left: 8px; bottom: 8px; font-size: 10.5px; color: #e9eaee;
  background: rgba(8, 9, 11, .62); border-radius: 999px; padding: 1px 7px;
}
.remove { position: absolute; top: 6px; right: 6px; padding: 5px; }
</style>
