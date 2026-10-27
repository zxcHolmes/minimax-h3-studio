<script setup>
import { onUnmounted, ref, watch } from 'vue'
import { PhPlus, PhX } from '@phosphor-icons/vue'

// v-model is a list of { id, file, desc }; position i is <Picture i+1> (or <Video i+1> with `video`) and
// <Subject first+i> in the prompt.
const items = defineModel({ type: Array, default: () => [] })
const props = defineProps({ max: { type: Number, default: 6 }, video: Boolean, subjects: { type: Boolean, default: true }, first: { type: Number, default: 1 } })
const kind = props.video ? 'video' : 'image'
const noun = props.video ? 'Video' : 'Picture'

const previews = ref({})
const dragging = ref(false)

watch(items, (list) => {
  const next = {}
  for (const it of list) next[it.id] = previews.value[it.id] || URL.createObjectURL(it.file)
  for (const [id, url] of Object.entries(previews.value)) if (!next[id]) URL.revokeObjectURL(url)
  previews.value = next
}, { immediate: true, deep: true })

onUnmounted(() => Object.values(previews.value).forEach((u) => URL.revokeObjectURL(u)))

let seq = 0
function add(files) {
  const room = props.max - items.value.length
  const picked = [...(files || [])].filter((f) => f.type.startsWith(`${kind}/`)).slice(0, room)
  if (picked.length) {
    items.value = [...items.value, ...picked.map((file) => ({ id: `${Date.now()}-${seq++}`, file, desc: '' }))]
  }
}

function remove(id) {
  items.value = items.value.filter((it) => it.id !== id)
}
</script>

<template>
  <div class="refs">
    <div v-for="(it, i) in items" :key="it.id" class="ref">
      <div class="thumb">
        <video v-if="video" :src="previews[it.id]" muted loop playsinline preload="metadata"
          @mouseenter="$event.target.play()" @mouseleave="$event.target.pause()" />
        <img v-else :src="previews[it.id]" :alt="`Reference ${i + 1}`" />
        <span class="badge mono">{{ noun }} {{ i + 1 }}<template v-if="subjects"> · Subject {{ first + i }}</template></span>
        <button type="button" class="btn icon remove" :aria-label="`Remove reference ${i + 1}`" @click="remove(it.id)">
          <PhX :size="13" weight="bold" />
        </button>
      </div>
      <input
        v-if="subjects"
        v-model="it.desc"
        class="input desc"
        type="text"
        :aria-label="`Subject description for reference ${noun.toLowerCase()} ${i + 1}`"
        :placeholder="video ? 'What it shows, e.g. the jogging man on the beach' : 'Describe the subject'"
      />
    </div>

    <label
      v-if="items.length < max"
      class="add"
      :class="{ dragging }"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="dragging = false; add($event.dataTransfer.files)"
    >
      <input type="file" :accept="`${kind}/*`" multiple class="sr-only" :aria-label="`Add reference ${kind}s`" @change="add($event.target.files); $event.target.value = ''" />
      <PhPlus :size="20" />
      <span>Add {{ kind }}s</span>
      <span class="count mono">{{ items.length }}/{{ max }}</span>
    </label>
  </div>
</template>

<style scoped>
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
/* minmax(0, 1fr): a plain 1fr column grows to a wide image's intrinsic width and skews the grid. */
.refs { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.ref { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.thumb {
  position: relative; aspect-ratio: 4 / 3; border-radius: var(--r-card); overflow: hidden; background: var(--screen);
}
.thumb img, .thumb video { width: 100%; height: 100%; object-fit: cover; display: block; }
.badge {
  position: absolute; left: 7px; bottom: 7px; font-size: 10.5px; color: #e9eaee;
  background: rgba(8, 9, 11, .62); border-radius: 999px; padding: 1px 7px;
}
.remove { position: absolute; top: 6px; right: 6px; padding: 5px; }
.desc { font-size: 12.5px; padding: 6px 9px; }
.add {
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;
  aspect-ratio: 4 / 3; align-self: start; border: 1.5px dashed var(--line); border-radius: var(--r-card);
  background: var(--surface-sunk); color: var(--muted); font-size: 12.5px; cursor: pointer;
  transition: border-color .15s, color .15s;
}
.add:hover, .add.dragging { border-color: var(--accent); color: var(--accent); }
.count { font-size: 10.5px; }
</style>
