import { useEffect, useState } from 'react'

export async function api(path, { method = 'GET', data, signal } = {}) {
  const form = data instanceof FormData
  const response = await fetch('/api' + path, {
    method, signal, body: data === undefined ? undefined : form ? data : JSON.stringify(data),
    headers: data === undefined || form ? undefined : { 'Content-Type': 'application/json' },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : 'No se pudo completar la operación.')
  }
  return response.headers.get('content-type')?.includes('application/json') ? response.json() : response.blob()
}


export function useData(path, revision) {
  const [result, setResult] = useState(null)
  useEffect(() => {
    let live = true
    if (path) api(path).then(data => { if (live) setResult({ path, data, error: '' }) })
      .catch(err => { if (live) setResult({ path, data: null, error: err.message }) })
    return () => { live = false }
  }, [path, revision])
  return path && result?.path === path ? [result.data, result.error] : [null, '']
}
