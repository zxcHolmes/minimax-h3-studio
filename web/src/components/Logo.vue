<script setup>
// Same mark as public/logo.svg, drawn with theme tokens. `live` makes the tally light blink while rendering.
defineProps({ size: { type: Number, default: 24 }, live: Boolean })
</script>

<template>
  <svg class="logo" :class="{ live }" :width="size" :height="size" viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <rect width="32" height="32" rx="8" class="tile" />
    <g class="ink" stroke-linecap="round" stroke-linejoin="round">
      <path d="M9 9V23" stroke-width="3" />
      <path d="M23 9V23" stroke-width="3" />
      <path d="M9 16H11.8L13.8 13.2L16 18.8L18.2 13.2L20.2 16H23" stroke-width="2.1" />
    </g>
    <circle class="tally" cx="26.3" cy="5.7" r="2.1" />
  </svg>
</template>

<style scoped>
.logo { flex: none; display: block; }
.tile { fill: var(--accent); }
.ink { stroke: var(--accent-ink); }
.tally { fill: var(--live); }
.live .tally { animation: tally 1.4s ease-in-out infinite; }
@keyframes tally { 50% { opacity: .25; } }
@media (prefers-reduced-motion: reduce) { .live .tally { animation: none; } }
</style>
