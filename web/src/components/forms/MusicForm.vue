<script setup>
import { computed, ref, toRefs } from 'vue'
import { useDraft, useJobSubmission, fileFrom } from '../../composables/useGeneration'
import { shortModel } from '../../models'
import FormFooter from './FormFooter.vue'
const MUSIC_CAPTION_HINT = `Global Metadata: Lo-fi hip-hop, 78 BPM, D flat major. Laid-back and dreamy, late-night study mood.

Vocal Details: Soft androgynous vocal, hushed half-sung delivery, sitting low in the mix.

Arrangement: Dusty boom-bap drums, warm Rhodes chords, mellow jazzy guitar, vinyl crackle.`
const MUSIC_LYRICS_HINT = `[Intro]
Mmm...

[Verse]
Midnight and the canvas glows

[Chorus]
Let it render on

[Outro]
Ooh... goodnight`


const props = defineProps({ music: Object, ready: Boolean })
const emit = defineEmits(['created'])
const draft = useDraft('music', { musicCaption: '', musicLyrics: '', musicDuration: 120 })
const { musicCaption, musicLyrics, musicDuration } = toRefs(draft)
const { seed, submitting, error, send } = useJobSubmission(emit)
const musicRange = computed(() => props.music?.duration_range || [10, 300])
function clock(s) { return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}` }
const musicLength = computed(() => clock(musicDuration.value))
// Rough length the lyrics need: about 0.6 s per sung Chinese character (or English word), a few seconds
// per section for breaths and fills, plus intro and outro. The duration is only a cap, so err long.
const lyricsNeed = computed(() => {
  const text = musicLyrics.value
  const sections = (text.match(/\[[^\]]+\]/g) || []).length
  const sung = text.replace(/\[[^\]]+\]/g, '')
  const units = (sung.match(/[\u3400-\u9fff]/g) || []).length + (sung.match(/[A-Za-z']+/g) || []).length
  if (!units) return null
  const [lo, hi] = musicRange.value
  return Math.min(hi, Math.max(lo, Math.ceil((units * 0.6 + sections * 4 + 15) / 10) * 10))
})
const lyricsTooShort = computed(() => lyricsNeed.value !== null && musicDuration.value < lyricsNeed.value)
// Measured on the RTX 4090: writing the acoustic tokens dominates and grows with the song length.
const MUSIC_SECONDS_PER_SECOND = 1.3
const musicEstimate = computed(() => Math.round(20 + MUSIC_SECONDS_PER_SECOND * musicDuration.value))

const canSubmit = computed(() => props.ready && !submitting.value && !!musicCaption.value.trim())
function submit() { if (canSubmit.value) return send({ kind: 'music', prompt: musicCaption.value, lyrics: musicLyrics.value, duration: musicDuration.value }) }
function reuse(job) {
  musicCaption.value = job.prompt; musicLyrics.value = job.lyrics || ''; musicDuration.value = Math.round(job.duration); seed.value = String(job.seed)
}
defineExpose({ reuse })
</script>
<template>
  <form class="generation-form" @submit.prevent="submit">

      <div class="field">
        <label for="music-caption" class="field-label">Caption<span class="aside">Style, mood, vocals, arrangement</span></label>
        <textarea
          id="music-caption"
          v-model="musicCaption"
          class="textarea"
          rows="8"
          spellcheck="false"
          :placeholder="MUSIC_CAPTION_HINT"
        />
        <p class="help">Write three parts: Global Metadata (genre, BPM, key, mood), Vocal Details and Arrangement. The more specific, the closer the result.</p>
      </div>

      <div class="field">
        <label for="music-lyrics" class="field-label">Lyrics<span class="aside">Empty for an instrumental</span></label>
        <textarea
          id="music-lyrics"
          v-model="musicLyrics"
          class="textarea mono raw"
          rows="10"
          spellcheck="false"
          :placeholder="MUSIC_LYRICS_HINT"
        />
        <p class="help">Section tags such as [Intro], [Verse], [Chorus], [Bridge], [Instrumental] and [Outro] set the song structure.</p>
      </div>

      <div class="field">
        <label for="music-duration" class="field-label">
          <span>Maximum length</span>
          <span class="aside mono">{{ musicLength }}</span>
        </label>
        <input
          id="music-duration"
          v-model.number="musicDuration"
          class="range"
          type="range"
          :min="musicRange[0]"
          :max="musicRange[1]"
          step="10"
        />
        <p v-if="lyricsTooShort" class="help warn">
          The lyrics need about {{ clock(lyricsNeed) }}; at {{ musicLength }} the song will be cut off.
          <button type="button" class="btn quiet small" @click="musicDuration = lyricsNeed">Use {{ clock(lyricsNeed) }}</button>
        </p>
        <p v-else class="help">The model may end the song earlier.<template v-if="lyricsNeed"> The lyrics need about {{ clock(lyricsNeed) }}.</template></p>
        <dl v-if="music" class="models">
          <div><dt>Model</dt><dd class="mono" :title="music.models.unet">{{ shortModel(music.models.unet) }}</dd></div>
          <div><dt>Sampler</dt><dd class="mono">{{ music.models.sampler }} · {{ music.models.steps }} steps · cfg {{ music.models.cfg }}</dd></div>
        </dl>
      </div>

    <FormFooter v-model:seed="seed" :ready="ready" :submitting="submitting" :can-submit="canSubmit" :error="error" label="Generate music">
      <span class="mono">≤ {{ musicLength }}</span><span class="muted">About {{ musicEstimate }} s</span>
    </FormFooter>
  </form>
</template>
