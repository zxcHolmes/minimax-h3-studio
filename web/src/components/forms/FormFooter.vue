<script setup>
import { PhShuffle } from '@phosphor-icons/vue'
const seed = defineModel('seed', { default: '' })
defineProps({ ready: Boolean, submitting: Boolean, canSubmit: Boolean, error: String, label: String })
</script>
<template>
  <div class="field">
    <label for="seed" class="field-label">Seed<span class="aside">Empty for random</span></label>
    <div class="seed">
      <input id="seed" v-model="seed" class="input mono" type="text" inputmode="numeric" placeholder="Random" />
      <button type="button" class="btn icon" aria-label="Pick a random seed" @click="seed = String(Math.floor(Math.random() * 2 ** 40))"><PhShuffle :size="16" /></button>
    </div>
  </div>
  <div class="submit">
    <span class="estimate"><slot /></span>
    <button class="btn primary go" :disabled="!canSubmit">{{ submitting ? 'Submitting' : label }}</button>
  </div>
  <p v-if="!ready" class="help">The server is still loading models; you can submit once it is ready.</p>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
</template>
