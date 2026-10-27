import { computed } from 'vue'

const SECTION_RE = /^\s*integrated_multimodal_description:\s*([\s\S]*?)\n\s*\n\s*overall_soundscape:\s*([\s\S]*?)\n\s*\n\s*non_diegetic_music:\s*([\s\S]*?)\s*$/
const REF_SECTION_RE = /\n\s*detailed_description:\s*([\s\S]*?)\n\s*\n\s*overall_soundscape:\s*([\s\S]*?)\n\s*\n\s*non_diegetic_music:\s*([\s\S]*?)\s*$/
const SUBJECT_RE = /^<Subject (\d+)> is ([\s\S]*?), as shown in <(?:Picture|Video) \d+>\.$/gm

export function useVideoPrompt({ mode, refs, refVideos, frames, rawMode, raw, sections, error }) {
function assemble(s) {
  return `integrated_multimodal_description: ${s.picture.trim()}\n\n` +
    `overall_soundscape: ${s.sound.trim() || 'N/A'}\n\n` +
    `non_diegetic_music: ${s.score.trim() || 'N/A'}`
}

// With no reference images the ref2va model runs on the prompt alone: no subjects to define or retain.
function assembleRef(s) {
  const sources = [
    ...refs.value.map((r, i) => ({ desc: r.desc, tag: `<Picture ${i + 1}>`, keep: `Preserve the same appearance as in <Picture ${i + 1}>.` })),
    ...refVideos.value.map((r, i) => ({ desc: r.desc, tag: `<Video ${i + 1}>`, keep: `Follow <Video ${i + 1}>.` })),
  ]
  const tags = sources.map((_, i) => i + 1)
  const seconds = (frames.value / 24).toFixed(4)
  const names = tags.map((i) => `<Subject ${i}>`)
  const featuring = names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0]
  const subjects = tags.length
    ? 'subject_definitions:\n' +
      sources.map((r, i) => `<Subject ${i + 1}> is ${r.desc.trim() || 'the subject'}, as shown in ${r.tag}.`).join('\n') + '\n\n'
    : ''
  const retention = tags.length
    ? '\n\nretention_analysis:\n' +
      sources.map((r, i) => `<Subject ${i + 1}> (appears in [Shot 1]): fully_preserved - ${r.keep}`).join('\n')
    : ''
  return subjects +
    `summary:\n[reference generation] A continuous ${seconds}-second video` + (featuring ? ` featuring ${featuring}` : '') + ', as described below.' +
    retention +
    `\n\ndetailed_description:\n${s.picture.trim()}` +
    `\n\noverall_soundscape:\n${s.sound.trim() || 'N/A'}` +
    `\n\nnon_diegetic_music:\n${s.score.trim() || 'N/A'}`
}

// Split a prompt back into the form's sections; null when it is not in a layout the form writes.
function parse(text, m = mode.value) {
  const hit = m === 'r2v' ? text.match(REF_SECTION_RE) : text.match(SECTION_RE)
  if (!hit) return null
  const clean = (v) => (v.trim() === 'N/A' ? '' : v.trim())
  return {
    sections: { picture: hit[1].trim(), sound: clean(hit[2]), score: clean(hit[3]) },
    descs: m === 'r2v' ? [...text.matchAll(SUBJECT_RE)].map((x) => (x[2] === 'the subject' ? '' : x[2])) : [],
  }
}

const prompt = computed(() => {
  if (rawMode.value) return raw.value
  return mode.value === 'r2v' ? assembleRef(sections.value) : assemble(sections.value)
})
const hasContent = computed(() => (rawMode.value ? raw.value.trim() : sections.value.picture.trim()))

function applyDescs(descs) {
  const items = [...refs.value, ...refVideos.value]
  descs.forEach((d, i) => { if (items[i]) items[i].desc = d })
}

function toggleRaw() {
  if (!rawMode.value) {
    raw.value = hasContent.value ? prompt.value : ''
    rawMode.value = true
    return
  }
  const parsed = raw.value.trim() ? parse(raw.value) : { sections: { picture: '', sound: '', score: '' }, descs: [] }
  if (parsed) {
    sections.value = parsed.sections
    applyDescs(parsed.descs)
    rawMode.value = false
  } else {
    error.value = 'This prompt does not follow the section layout; keep editing it as a raw prompt.'
  }
}

function loadPrompt(text, m) {
  const parsed = parse(text, m)
  if (parsed) {
    sections.value = parsed.sections
    rawMode.value = false
  } else {
    raw.value = text
    rawMode.value = true
  }
  return parsed?.descs || []
}

  return { prompt, hasContent, toggleRaw, loadPrompt }
}
