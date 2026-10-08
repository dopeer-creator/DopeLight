import type { JobEvent } from '@shared/types'
import { useBackendStore } from './stores/backendStore'

/** Calls to the local backend, with the per-launch token attached. */

export class BackendError extends Error {}

function connection(): { baseUrl: string; token: string } {
  const { baseUrl, token, state } = useBackendStore.getState().info
  if (state !== 'running' || baseUrl === null || token === null) {
    throw new BackendError('The backend is not running yet.')
  }
  return { baseUrl, token }
}

export async function backendFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const { baseUrl, token } = connection()
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${token}` }
  })
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // not JSON; keep the status code
    }
    throw new BackendError(detail)
  }
  return response
}

/** Progress events of a job, until it ends. */
export async function* jobEvents(jobId: string): AsyncGenerator<JobEvent> {
  const response = await backendFetch(`/jobs/${jobId}/events`)
  const reader = response.body!.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) return
    buffer += value
    let end = buffer.indexOf('\n\n')
    while (end !== -1) {
      const line = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      if (line.startsWith('data: ')) yield JSON.parse(line.slice(6)) as JobEvent
      end = buffer.indexOf('\n\n')
    }
  }
}
