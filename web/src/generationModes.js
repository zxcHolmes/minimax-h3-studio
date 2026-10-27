import { PhCube, PhFilmStrip, PhImage, PhMusicNotes, PhTextT, PhUserFocus } from '@phosphor-icons/vue'

// Navigation and form routing share one registry. New families add an entry here.
export const generationModes = [
  { id: 't2v', family: 'video', group: 'VIDEO', label: 'Text to video', model: 'MiniMax-H3 / FastH3', icon: PhTextT },
  { id: 'i2v', family: 'video', group: 'VIDEO', label: 'Animate frames', model: 'MiniMax-H3 / FastH3', icon: PhFilmStrip },
  { id: 'r2v', family: 'video', group: 'VIDEO', label: 'Reference to video', model: 'FastH3 OmniRef', icon: PhUserFocus },
  { id: 't2i', family: 'picture', imageModel: 'moss', group: 'IMAGE', label: 'MOSS-Image', model: 'MOSS-Image', hint: 'Generate', short: 'MO', icon: PhImage },
  { id: 'flux-klein-4b', family: 'picture', imageModel: 'flux-klein-4b', group: 'IMAGE', label: 'FLUX.2 Klein 4B', model: '4-step · Generate & edit', hint: '4-step · Generate & edit', short: 'FL', icon: PhImage },
  { id: 'qwen-image-21-turbo', family: 'picture', imageModel: 'qwen-image-21-turbo', group: 'IMAGE', label: 'Qwen Image 2.1', model: '8-step Turbo · Generate & edit', hint: '8-step Turbo · Generate & edit', short: 'QW', icon: PhImage },
  { id: 't2m', family: 'music', group: 'AUDIO', label: 'Compose music', model: 'MiniMax Music 3', icon: PhMusicNotes },
  { id: 'i23d', family: 'mesh', group: '3D', label: 'Image to 3D', model: 'Pixal3D', icon: PhCube },
]
export function initialMode() {
  try {
    const saved = localStorage.getItem('h3.mode') || JSON.parse(localStorage.getItem('h3.form.v2'))?.mode
    if (generationModes.some((m) => m.id === saved)) return saved
  } catch { /* storage unavailable */ }
  return 't2v'
}

export const historyTypes = {
  video: { kind: 'video', label: 'Videos', empty: 'Your generated videos and upscales will appear here.' },
  picture: { kind: 'image', label: 'Pictures', empty: 'Your generated pictures will appear here.' },
  music: { kind: 'music', label: 'Music', empty: 'Your generated songs will appear here.' },
  mesh: { kind: '3d', label: '3D models', empty: 'Your generated 3D models will appear here.' },
}

export function imageMode(model = 'moss') {
  return generationModes.find((m) => m.imageModel === model)?.id || 't2i'
}
export function historyForMode(mode) {
  const current = generationModes.find((m) => m.id === mode) || generationModes[0]
  const history = historyTypes[current.family]
  return current.family === 'picture'
    ? { ...history, imageModel: current.imageModel, label: `${current.label} pictures` }
    : history
}
