async function request(method, url, body) {
  const res = await fetch(url, { method, body })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`)
  return data
}

export const api = {
  health: () => request('GET', '/api/health'),
  presets: () => request('GET', '/api/presets'),
  // One page of jobs, newest first, plus the total from X-Total-Count.
  jobs: async (limit, offset = 0) => {
    const res = await fetch(`/api/jobs?limit=${limit}&offset=${offset}`)
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    const items = await res.json()
    return { items, total: Number(res.headers.get('X-Total-Count') ?? items.length) }
  },
  create: (form) => request('POST', '/api/jobs', form),
  cancel: (id) => request('POST', `/api/jobs/${id}/cancel`),
  remove: (id) => request('DELETE', `/api/jobs/${id}`),
}
