async function request(method, url, body) {
  const res = await fetch(url, { method, body })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`)
  return data
}

export const api = {
  health: () => request('GET', '/api/health'),
  presets: () => request('GET', '/api/presets'),
  jobs: (limit = 60) => request('GET', `/api/jobs?limit=${limit}`),
  create: (form) => request('POST', '/api/jobs', form),
  cancel: (id) => request('POST', `/api/jobs/${id}/cancel`),
  remove: (id) => request('DELETE', `/api/jobs/${id}`),
}
