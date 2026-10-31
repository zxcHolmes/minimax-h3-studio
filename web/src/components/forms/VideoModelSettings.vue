<script setup>
import { shortModel } from '../../models'
const resolution = defineModel('resolution')
const lora = defineModel('lora')
const strength = defineModel('strength')
const sampler = defineModel('sampler')
defineProps({ resolutions: Array, groupOptions: Array, group: String, loraOptions: Array,
  recommended: String, currentLora: Object, strengthRange: Array, samplerChoosable: Boolean,
  samplers: Array, effectiveSampler: String })
const emit = defineEmits(['pick-group'])
</script>
<template>
    <div class="field">
      <span class="field-label">Resolution</span>
      <div class="presets">
        <button
          v-for="r in resolutions"
          :key="r.id"
          type="button"
          class="preset"
          :class="{ on: resolution === r.id }"
          :aria-pressed="resolution === r.id"
          @click="resolution = r.id"
        >
          <span class="preset-name">{{ r.id }}</span>
          <span class="preset-meta mono">{{ r.sizes['16:9'].join('×') }}</span>
        </button>
      </div>
    </div>

    <div class="field">
      <span class="field-label">Model<span class="aside">The base model follows the mode</span></span>
      <div class="presets groups">
        <button
          v-for="g in groupOptions"
          :key="g.id"
          type="button"
          class="preset"
          :class="{ on: group === g.id }"
          :aria-pressed="group === g.id"
          @click="emit('pick-group', g.id)"
        >
          <span class="preset-name">{{ g.label }}</span>
          <span class="preset-meta mono">{{ g.lora ? 'base + LoRA' : 'distilled, no LoRA' }}</span>
        </button>
      </div>
      <div class="loras" role="radiogroup" :aria-label="group === 'h3' ? 'LoRA' : 'Model'">
        <button
          v-for="l in loraOptions"
          :key="l.id"
          type="button"
          role="radio"
          class="lora"
          :class="{ on: lora === l.id }"
          :aria-checked="lora === l.id"
          @click="lora = l.id"
        >
          <span class="lora-name">{{ l.label }}<span v-if="l.id === recommended" class="pill">Recommended</span></span>
          <span class="lora-meta mono">{{ l.steps }} steps</span>
        </button>
      </div>
      <div v-if="currentLora?.models.lora" class="strength">
        <label for="strength" class="section-label">LoRA strength</label>
        <input
          id="strength"
          v-model.number="strength"
          type="range"
          :min="strengthRange?.[0] ?? 0"
          :max="strengthRange?.[1] ?? 2"
          step="0.05"
        />
        <span class="mono strength-value">{{ strength.toFixed(2) }}</span>
        <button v-if="strength !== 1" type="button" class="btn quiet small" @click="strength = 1">Reset</button>
      </div>
      <div v-if="samplerChoosable" class="sampler">
        <span class="section-label">Sampler</span>
        <div class="chips">
          <button
            v-for="s in samplers"
            :key="s"
            type="button"
            class="chip"
            :class="{ on: effectiveSampler === s }"
            :aria-pressed="effectiveSampler === s"
            @click="sampler = s === currentLora.models.sampler ? '' : s"
          >{{ s }}<template v-if="s === currentLora.models.sampler"> (default)</template></button>
        </div>
      </div>
      <dl v-if="currentLora" class="models">
        <div><dt>Base</dt><dd class="mono" :title="currentLora.models.unet">{{ shortModel(currentLora.models.unet) }}</dd></div>
        <div v-if="currentLora.models.lora"><dt>LoRA</dt><dd class="mono" :title="currentLora.models.lora">{{ shortModel(currentLora.models.lora) }} × {{ strength.toFixed(2) }}</dd></div>
        <div>
          <dt>Sampler</dt>
          <dd class="mono">{{ effectiveSampler }} · {{ currentLora.steps }} steps · shift {{ currentLora.models.shift_video }}/{{ currentLora.models.shift_audio }}</dd>
        </div>
        <div v-if="currentLora.models.attention"><dt>Attn</dt><dd class="mono">{{ currentLora.models.attention }}</dd></div>
      </dl>
    </div>

</template>
