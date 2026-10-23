<script setup>
import { nextTick, ref } from 'vue'

// One modal confirmation on the native <dialog>: Esc and the backdrop cancel, focus stays inside.
// ask() resolves true when the user confirms.
const el = ref(null)
const cancelBtn = ref(null)
const opts = ref({})
let settle = null

async function ask(options) {
  settle?.(false)
  opts.value = options
  await nextTick()
  el.value.showModal()
  // Start on Cancel so Enter does not delete by accident.
  cancelBtn.value?.focus()
  return new Promise((resolve) => { settle = resolve })
}

function close(result) {
  const resolve = settle
  settle = null
  if (el.value?.open) el.value.close()
  resolve?.(result)
}

function onBackdrop(e) {
  if (e.target === el.value) close(false)
}

defineExpose({ ask })
</script>

<template>
  <dialog ref="el" class="confirm" aria-labelledby="confirm-title" @cancel.prevent="close(false)" @click="onBackdrop">
    <div class="body">
      <img v-if="opts.image" class="preview" :src="opts.image" alt="" />
      <div class="text">
        <h2 id="confirm-title">{{ opts.title }}</h2>
        <p v-if="opts.detail" class="detail">{{ opts.detail }}</p>
        <p v-if="opts.message" class="message">{{ opts.message }}</p>
      </div>
    </div>
    <footer>
      <button ref="cancelBtn" type="button" class="btn" @click="close(false)">Cancel</button>
      <button type="button" class="btn destructive" @click="close(true)">{{ opts.confirmLabel || 'Delete' }}</button>
    </footer>
  </dialog>
</template>

<style scoped>
.confirm {
  width: min(420px, calc(100vw - 32px));
  padding: 0;
  border: 1px solid var(--line);
  border-radius: var(--r-card);
  background: var(--surface);
  color: var(--text);
  box-shadow: var(--shadow);
}
.confirm[open] { animation: rise .16s ease-out; }
.confirm::backdrop { background: rgba(13, 14, 17, .45); backdrop-filter: blur(2px); }
.body { display: flex; gap: 14px; padding: 20px 20px 16px; }
.preview {
  width: 96px; aspect-ratio: 16 / 9; flex: none; object-fit: cover;
  border-radius: 8px; background: var(--screen);
}
.text { min-width: 0; }
h2 { margin: 0 0 6px; font-size: 15px; font-weight: 600; }
.detail {
  margin: 0 0 6px; font-size: 13px; color: var(--text-2);
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.message { margin: 0; font-size: 12px; color: var(--muted); }
footer {
  display: flex; justify-content: flex-end; gap: 8px;
  padding: 12px 20px; border-top: 1px solid var(--line); background: var(--surface-sunk);
  border-radius: 0 0 var(--r-card) var(--r-card);
}
.btn.destructive { background: var(--live); border-color: var(--live); color: #fff; font-weight: 600; }
.btn.destructive:hover { filter: brightness(1.08); }
@keyframes rise { from { opacity: 0; transform: translateY(6px) scale(.98); } }
@media (prefers-reduced-motion: reduce) { .confirm[open] { animation: none; } }
</style>
