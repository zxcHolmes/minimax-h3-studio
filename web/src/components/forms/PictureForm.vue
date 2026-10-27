<script setup>
import { computed, ref, toRefs } from 'vue'
import { useDraft, useJobSubmission, fileFrom } from '../../composables/useGeneration'
import { shortModel } from '../../models'
import FormFooter from './FormFooter.vue'
const props = defineProps({ picture: Object, aspects: Array, ready: Boolean })
const emit = defineEmits(['created'])
const draft = useDraft('picture', { picPrompt: '', picAspect: '1:1' })
const { picPrompt, picAspect } = toRefs(draft)
const { seed, submitting, error, send } = useJobSubmission(emit)
const pictureSize = computed(() => props.picture?.sizes?.[picAspect.value])
const canSubmit = computed(() => props.ready && !submitting.value && !!picPrompt.value.trim())
function submit() { if (canSubmit.value) return send({ kind: 'image', prompt: picPrompt.value, aspect_ratio: picAspect.value }) }
function reuse(job) {
  picPrompt.value = job.prompt
  seed.value = String(job.seed)
  const match = Object.entries(props.picture?.sizes || {}).find(([, s]) => s[0] === job.width && s[1] === job.height)
  if (match) picAspect.value = match[0]
}
defineExpose({ reuse })
</script>
<template>
  <form class="generation-form" @submit.prevent="submit">


      <div class="field">
        <label for="pic-prompt" class="field-label">Prompt</label>
        <textarea
          id="pic-prompt"
          v-model="picPrompt"
          class="textarea"
          rows="7"
          spellcheck="false"
          placeholder="3D animated film style, a lion cub with a red mane, full body, front view, plain white background"
        />
        <p class="help">Describe subject, style, framing and background; a plain background works best for reference images.</p>
      </div>

      <div class="field">
        <span class="field-label">Aspect ratio</span>
        <div class="chips">
          <button
            v-for="a in aspects"
            :key="a"
            type="button"
            class="chip"
            :class="{ on: picAspect === a }"
            :aria-pressed="picAspect === a"
            @click="picAspect = a"
          >{{ a }}</button>
        </div>
        <dl v-if="picture" class="models">
          <div><dt>Model</dt><dd class="mono" :title="picture.models.unet">{{ shortModel(picture.models.unet) }}</dd></div>
          <div><dt>Sampler</dt><dd class="mono">{{ picture.models.sampler }} · {{ picture.models.steps }} steps · cfg {{ picture.models.cfg }}</dd></div>
        </dl>
      </div>

    <FormFooter v-model:seed="seed" :ready="ready" :submitting="submitting" :can-submit="canSubmit" :error="error" label="Generate picture">
      <span class="mono">{{ pictureSize?.join('×') }}</span><span class="muted">About 16 s</span>
    </FormFooter>
  </form>
</template>
