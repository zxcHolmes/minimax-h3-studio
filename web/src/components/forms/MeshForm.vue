<script setup>
import { computed, ref, toRefs } from 'vue'
import { useDraft, useJobSubmission, fileFrom } from '../../composables/useGeneration'
import FormFooter from './FormFooter.vue'
import ImageDrop from '../ImageDrop.vue'
const props = defineProps({ mesh: Object, ready: Boolean })
const emit = defineEmits(['created'])
const meshFile = ref(null)
const draft = useDraft('mesh', { meshResolution: 1024, textureSize: 2048, removeBackground: true })
const { meshResolution, textureSize, removeBackground } = toRefs(draft)
const { seed, submitting, error, send } = useJobSubmission(emit)
const canSubmit = computed(() => props.ready && !submitting.value && !!meshFile.value)
function submit() {
  if (canSubmit.value) return send({ kind: '3d', image: meshFile.value, mesh_resolution: meshResolution.value,
    texture_size: textureSize.value, remove_background: removeBackground.value })
}
async function reuse(job) {
  try {
    meshResolution.value = job.mesh_options?.resolution || 1024
    textureSize.value = job.mesh_options?.texture_size || 2048
    removeBackground.value = job.mesh_options?.remove_background ?? true
    seed.value = String(job.seed)
    meshFile.value = await fileFrom(job.image_url, job.image)
  } catch (e) { error.value = e.message }
}
async function useAs3D(job) {
  try { meshFile.value = await fileFrom(job.picture_url, job.picture) }
  catch (e) { error.value = e.message }
}
defineExpose({ reuse, useAs3D })
</script>
<template>
  <form class="generation-form" @submit.prevent="submit">

      <div class="field">
        <label class="field-label">Source image<span class="aside">One object, fully visible</span></label>
        <ImageDrop v-model="meshFile" label="3D source image" placeholder="Drop an image or click to choose" />
        <p class="help">Use a clear photo or illustration of a single object. Transparent PNGs work too.</p>
      </div>
      <div class="field">
        <span class="field-label">Geometry detail</span>
        <div class="pills">
          <button v-for="r in mesh?.resolutions || [1024, 1536]" :key="r" type="button" class="btn" :class="{ selected: meshResolution === r }" :aria-pressed="meshResolution === r" @click="meshResolution = r">{{ r }}<template v-if="r === 1024"> · Standard</template><template v-else> · Fine</template></button>
        </div>
      </div>
      <div class="field">
        <span class="field-label">Texture size</span>
        <div class="pills">
          <button v-for="r in mesh?.texture_sizes || [1024, 2048, 4096]" :key="r" type="button" class="btn" :class="{ selected: textureSize === r }" :aria-pressed="textureSize === r" @click="textureSize = r">{{ r / 1024 }}K</button>
        </div>
      </div>
      <label class="help"><input v-model="removeBackground" type="checkbox" /> Remove background automatically</label>
      <p class="help">Turn this off for images with transparency. The result includes geometry and PBR materials in a GLB file, ready to rotate, inspect and download.</p>

    <FormFooter v-model:seed="seed" :ready="ready" :submitting="submitting" :can-submit="canSubmit" :error="error" label="Generate 3D model">
      <span class="mono">GLB · {{ textureSize / 1024 }}K textures</span><span class="muted">Several minutes</span>
    </FormFooter>
  </form>
</template>
