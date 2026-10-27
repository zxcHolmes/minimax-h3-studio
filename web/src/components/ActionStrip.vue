<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
const rail = ref(null)
const items = ref(null)
const left = ref(false)
const right = ref(false)
let observer
function measure() {
  const el = rail.value
  if (!el) return
  left.value = el.scrollLeft > 2
  right.value = el.scrollLeft + el.clientWidth < el.scrollWidth - 2
}
function wheel(event) {
  const el = rail.value
  if (!el || el.scrollWidth <= el.clientWidth || Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return
  const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? el.clientWidth : 1)
  const next = Math.max(0, Math.min(el.scrollWidth - el.clientWidth, el.scrollLeft + delta))
  if (Math.abs(next - el.scrollLeft) > 1) { event.preventDefault(); el.scrollLeft = next }
}
function move(direction) { rail.value?.scrollBy({ left: direction * 140, behavior: 'smooth' }) }
onMounted(() => {
  observer = new ResizeObserver(measure)
  observer.observe(rail.value)
  observer.observe(items.value)
  measure()
})
onBeforeUnmount(() => observer?.disconnect())
</script>
<template>
  <div class="action-strip" :class="{ left, right }">
    <div ref="rail" class="rail" role="group" aria-label="Job actions; scroll horizontally for more" tabindex="0" @scroll.passive="measure" @wheel="wheel" @keydown.left.self.prevent="move(-1)" @keydown.right.self.prevent="move(1)">
      <div ref="items" class="items"><slot /></div>
    </div>
  </div>
</template>
<style scoped>
.action-strip { position: relative; min-width: 0; width: 100%; }
.rail { width: 100%; overflow-x: auto; overscroll-behavior-x: contain; scrollbar-width: thin; scrollbar-color: var(--line) transparent; padding: 4px 4px 8px; }
.items { display: flex; gap: 6px; align-items: center; width: max-content; min-width: 100%; }
.items :deep(.btn), .items :deep(.upscale) { flex: 0 0 auto; }
.action-strip::before, .action-strip::after { content: ''; position: absolute; top: 0; bottom: 10px; width: 16px; pointer-events: none; z-index: 1; opacity: 0; transition: opacity .15s; }
.action-strip::before { left: 0; background: linear-gradient(to right, var(--surface), transparent); }
.action-strip::after { right: 0; background: linear-gradient(to left, var(--surface), transparent); }
.action-strip.left::before, .action-strip.right::after { opacity: 1; }
.rail::-webkit-scrollbar { height: 4px; }
.rail::-webkit-scrollbar-thumb { background: var(--line); border-radius: 4px; }
</style>
