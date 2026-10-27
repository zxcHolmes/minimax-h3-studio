<script setup>
import { PhTextAlignLeft, PhRows } from '@phosphor-icons/vue'
const rawMode = defineModel('rawMode')
const raw = defineModel('raw')
const sections = defineModel('sections')
defineProps({ mode: String })
const emit = defineEmits(['toggle-raw'])
const SECTIONS = [
  { key: 'picture', tag: 'integrated_multimodal_description', label: 'Picture', rows: 6,
    help: 'Style, subject, action, camera and light. Put dialogue inline: <d>[English] Hello.</d>',
    refTag: 'detailed_description',
    refHelp: 'Refer to the reference subjects as <Subject 1>, <Subject 2>; describe action, camera and light. Put dialogue inline: <d>[English] Hello.</d>' },
  { key: 'sound', tag: 'overall_soundscape', label: 'Sound', rows: 2,
    help: 'Dialogue, ambience and sound effects.' },
  { key: 'score', tag: 'non_diegetic_music', label: 'Music', rows: 2,
    help: 'Background score. Leave empty for none.' },
]
const PICTURE_HINT = {
  t2v: 'Live-action, cinematic. A fisherman hauls a dripping net onto a wooden boat at sunrise...',
  i2v: 'Preserve the subject and scene from <Picture 1>, then describe the motion and camera...',
  r2v: 'Live-action, bright afternoon light. <Subject 1> rides <Subject 2> down a Paris street toward the camera...',
}
</script>
<template>
    <div class="field">
      <div class="field-label">
        <span>Prompt</span>
        <button type="button" class="btn quiet small" @click="emit('toggle-raw')">
          <component :is="rawMode ? PhRows : PhTextAlignLeft" :size="14" />
          {{ rawMode ? 'Sections' : 'Raw prompt' }}
        </button>
      </div>

      <textarea
        v-if="rawMode"
        v-model="raw"
        class="textarea mono raw"
        rows="12"
        spellcheck="false"
        aria-label="Raw prompt"
        placeholder="integrated_multimodal_description: ..."
      />
      <div v-else class="sections">
        <div v-for="s in SECTIONS" :key="s.key" class="section">
          <label :for="`sec-${s.key}`" class="section-label">
            {{ s.label }}<span class="mono tag">{{ mode === 'r2v' && s.refTag ? s.refTag : s.tag }}</span>
          </label>
          <textarea
            :id="`sec-${s.key}`"
            v-model="sections[s.key]"
            class="textarea"
            :rows="s.rows"
            spellcheck="false"
            :placeholder="s.key === 'picture' ? PICTURE_HINT[mode] : ''"
          />
          <p class="help">{{ mode === 'r2v' && s.refHelp ? s.refHelp : s.help }}</p>
        </div>
      </div>
      <p v-if="mode === 'i2v'" class="help">The first frame is &lt;Picture 1&gt; and the last frame &lt;Picture 2&gt;; the server adds these references if the prompt lacks them.</p>
      <p v-if="mode === 'r2v' && !rawMode" class="help">Subject definitions, summary and retention notes are generated from the images; open the raw prompt to see the full text.</p>
    </div>

</template>
