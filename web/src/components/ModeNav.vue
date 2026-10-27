<script setup>
import { computed } from 'vue'
import { generationModes } from '../generationModes'
const mode = defineModel({ default: 't2v' })
const groups = computed(() => [...new Set(generationModes.map((m) => m.group))].map((name) => ({ name, items: generationModes.filter((m) => m.group === name) })))
</script>
<template>
  <nav class="mode-nav" aria-label="Generation tools">
    <span class="nav-heading mono">CREATE</span>
    <div v-for="group in groups" :key="group.name" class="nav-group">
      <span class="group-name mono">{{ group.name }}</span>
      <button v-for="item in group.items" :key="item.id" type="button" :aria-label="item.label" :title="item.label" :class="{ active: mode === item.id }" :aria-current="mode === item.id ? 'page' : null" @click="mode = item.id">
        <component :is="item.icon" :size="19" :weight="mode === item.id ? 'duotone' : 'regular'" />
        <span>{{ item.label }}</span>
      </button>
    </div>
  </nav>
</template>
<style scoped>
.mode-nav { position: sticky; top: 88px; display: flex; flex-direction: column; gap: 23px; padding: 8px 0; }
.nav-heading { color: var(--text); font-size: 11px; letter-spacing: .14em; padding-left: 12px; }
.nav-group { display: flex; flex-direction: column; gap: 4px; }
.group-name { color: var(--muted); font-size: 9px; letter-spacing: .12em; margin: 0 12px 5px; }
button { display: flex; align-items: center; gap: 9px; width: 100%; border: 0; border-radius: 8px; padding: 10px 12px; background: transparent; color: var(--text-2); text-align: left; font-size: 12px; cursor: pointer; }
button:hover { background: var(--surface-sunk); color: var(--text); }
button.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
button svg { flex-shrink: 0; }
@media (max-width: 700px) {
  .mode-nav { top: 76px; gap: 20px; }
  .nav-heading, .group-name, button span { display: none; }
  button { justify-content: center; padding: 12px 6px; }
}
</style>
