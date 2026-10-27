<script setup>
import { computed, ref, toRefs } from 'vue'
import { useDraft, useJobSubmission, fileFrom } from '../../composables/useGeneration'
import { shortModel } from '../../models'
import RefImages from '../RefImages.vue'
import FormFooter from './FormFooter.vue'

const props = defineProps({ picture: Object, aspects: Array, ready: Boolean, imageModel: { type: String, default: 'moss' } })
const emit = defineEmits(['created'])
const choice = computed(() => props.picture?.choices?.find((m) => m.id === props.imageModel))
const models = computed(() => choice.value?.models || props.picture?.models)
const maxRefs = computed(() => choice.value?.max_refs || 0)
const draft = useDraft(props.imageModel === 'moss' ? 'picture' : `picture.${props.imageModel}`, { picPrompt: '', picAspect: '1:1', picEdit: false })
const { picPrompt, picAspect, picEdit } = toRefs(draft)
const refs = ref([])
const { seed, submitting, error, send } = useJobSubmission(emit)
const editing = computed(() => maxRefs.value > 0 && picEdit.value)
const followsInput = computed(() => editing.value && (props.imageModel === 'qwen-image-21-turbo' || picAspect.value === 'image'))
const effectiveAspect = computed(() => followsInput.value ? 'image' : picAspect.value === 'image' ? '1:1' : picAspect.value)
const pictureSize = computed(() => editing.value && followsInput.value ? null : (choice.value?.sizes || props.picture?.sizes)?.[effectiveAspect.value])
const canSubmit = computed(() => props.ready && !submitting.value && !!picPrompt.value.trim() && (!editing.value || refs.value.length > 0))
function submit() {
  if (!canSubmit.value) return
  const fields = new FormData()
  fields.append('kind', 'image')
  fields.append('image_model', props.imageModel)
  fields.append('prompt', picPrompt.value)
  fields.append('aspect_ratio', effectiveAspect.value)
  if (editing.value) refs.value.forEach((r) => fields.append('ref_image', r.file))
  return send(fields)
}
async function reuse(job) {
  error.value = ''
  picPrompt.value = job.prompt
  seed.value = String(job.seed)
  picEdit.value = job.mode === 'i2i'
  if (picEdit.value) {
    try {
      refs.value = await Promise.all((job.ref_urls || []).map(async (url, i) => ({ id: `reuse-${i}`, file: await fileFrom(url, job.refs[i]), desc: '' })))
      const match = props.imageModel !== 'qwen-image-21-turbo' && Object.entries(choice.value?.sizes || {}).find(([, size]) => size[0] === job.width && size[1] === job.height)
      picAspect.value = match ? match[0] : 'image'
    } catch (e) { error.value = e.message }
  } else {
    const sizes = choice.value?.sizes || props.picture?.sizes || {}
    const match = Object.entries(sizes).find(([, s]) => s[0] === job.width && s[1] === job.height)
    if (match) picAspect.value = match[0]
  }
}
async function useAsEdit(job) {
  try {
    const file = await fileFrom(job.picture_url, job.picture)
    refs.value = [{ id: `edit-${job.id}`, file, desc: '' }]
    picEdit.value = true
    picAspect.value = 'image'
    picPrompt.value = ''
    error.value = ''
  } catch (e) { error.value = e.message }
}
defineExpose({ reuse, useAsEdit })
</script>
<template>
  <form class="generation-form" @submit.prevent="submit">
    <div v-if="maxRefs" class="field">
      <span class="field-label">Task</span>
      <div class="chips">
        <button type="button" class="chip" :class="{ on: !picEdit }" :aria-pressed="!picEdit" @click="picEdit = false">Generate</button>
        <button type="button" class="chip" :class="{ on: picEdit }" :aria-pressed="picEdit" @click="picEdit = true; picAspect = 'image'">Edit images</button>
      </div>
    </div>
    <div v-if="editing" class="field">
      <span class="field-label">Input images<span class="aside">Up to {{ maxRefs }} · first image is the canvas</span></span>
      <RefImages v-model="refs" :subjects="false" :max="maxRefs" />
      <p class="help">Describe what to change and what to preserve.<template v-if="refs.length > 1"> Refer to the inputs as {{ imageModel === 'flux-klein-4b' ? 'image 1, image 2…' : '&lt;image1&gt;, &lt;image2&gt;…' }}.</template></p>
    </div>
    <div class="field">
      <label for="pic-prompt" class="field-label">{{ editing ? 'Edit instruction' : 'Prompt' }}</label>
      <textarea id="pic-prompt" v-model="picPrompt" class="textarea" rows="7" spellcheck="false"
        :placeholder="editing ? 'Give the zebra a red knitted scarf. Preserve its pose, stripes and the white background.' : '3D animated film style, a young zebra foal, full body, side view, plain white background'" />
      <p class="help">{{ editing ? 'A precise change works best. Keep the parts you want to preserve in the instruction.' : 'Describe subject, style, framing and background.' }}</p>
    </div>
    <div class="field">
      <span class="field-label">Aspect ratio</span>
      <p v-if="editing && imageModel === 'qwen-image-21-turbo'" class="help">Follows the first input image, around one megapixel.</p>
      <div v-else class="chips">
        <button v-if="editing" type="button" class="chip" :class="{ on: picAspect === 'image' }" @click="picAspect = 'image'">Follow input</button>
        <button v-for="a in aspects" :key="a" type="button" class="chip" :class="{ on: picAspect === a }" :aria-pressed="picAspect === a" @click="picAspect = a">{{ a }}</button>
      </div>
      <dl v-if="models" class="models">
        <div><dt>Model</dt><dd class="mono" :title="models.unet">{{ shortModel(models.unet) }}</dd></div>
        <div><dt>Sampler</dt><dd class="mono">{{ models.sampler }} · {{ models.steps }} steps · cfg {{ models.cfg }}</dd></div>
      </dl>
    </div>
    <FormFooter v-model:seed="seed" :ready="ready" :submitting="submitting" :can-submit="canSubmit" :error="error" :label="editing ? 'Edit picture' : 'Generate picture'">
      <span class="mono">{{ pictureSize?.join('×') || 'Matches input' }}</span>
      <span class="muted">{{ models?.steps }} steps<template v-if="editing"> · {{ refs.length }} input{{ refs.length === 1 ? '' : 's' }}</template></span>
    </FormFooter>
  </form>
</template>
