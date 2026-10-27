import { reactive, ref, watch } from 'vue'
import { api } from '../api'

// Each model family owns its draft; migrate the original combined form once.
export function useDraft(kind, defaults) {
  const key = `h3.form.${kind}`
  let saved = {}
  try { saved = JSON.parse(localStorage.getItem(key) || localStorage.getItem('h3.form.v2')) || {} } catch { /* private mode */ }
  const draft = reactive(Object.fromEntries(Object.entries(defaults).map(([k, v]) => [k, saved[k] ?? v])))
  watch(draft, () => { try { localStorage.setItem(key, JSON.stringify(draft)) } catch { /* quota */ } })
  return draft
}

export async function fileFrom(url, name) {
  const response = await fetch(url)
  if (!response.ok) throw new Error('The source file is no longer available.')
  const blob = await response.blob()
  return new File([blob], name, { type: blob.type })
}

export function useJobSubmission(emit) {
  const seed = ref('')
  const submitting = ref(false)
  const error = ref('')
  async function send(fields) {
    if (submitting.value) return
    error.value = ''
    submitting.value = true
    try {
      const form = fields instanceof FormData ? fields : new FormData()
      if (!(fields instanceof FormData)) {
        for (const [key, value] of Object.entries(fields)) if (value != null) form.append(key, value)
      }
      if (seed.value.trim()) form.set('seed', seed.value.trim())
      emit('created', await api.create(form))
    } catch (e) { error.value = e.message }
    finally { submitting.value = false }
  }
  return { seed, submitting, error, send }
}
