import { create } from 'zustand'
import type { SessionInfo, SessionResponse } from '@shared/types'
import { backendFetch, jobEvents } from '../api'
import type { RelightMaps } from '../gl/renderer'
import { depthFromUint16 } from '../parity'
import { starterLights, useLightsStore } from './lightsStore'

export type SessionStatus = 'empty' | 'working' | 'ready' | 'error'

/** A picked, dropped, or pasted image. */
export interface ImageSource {
  name: string
  data: Blob
}

interface SessionStore {
  status: SessionStatus
  /** 0..1 while working. */
  progress: number
  message: string
  error: string | null
  sourceName: string | null
  sessionId: string | null
  maps: RelightMaps | null
  open: (source: ImageSource) => Promise<void>
  cancel: () => void
}

// Decode PNG bytes exactly: no colour management, no alpha premultiply.
const RAW_BITMAP: ImageBitmapOptions = { colorSpaceConversion: 'none', premultiplyAlpha: 'none' }

async function fetchBitmap(path: string): Promise<ImageBitmap> {
  return createImageBitmap(await (await backendFetch(path)).blob(), RAW_BITMAP)
}

async function fetchMaps(sessionId: string): Promise<RelightMaps> {
  const info = (await (await backendFetch(`/session/${sessionId}`)).json()) as SessionInfo
  const [albedo, normal, normalSmooth, aux, detail, depthBytes, thicknessBytes] = await Promise.all([
    fetchBitmap(`/session/${sessionId}/albedo_proxy`),
    fetchBitmap(`/session/${sessionId}/normal`),
    fetchBitmap(`/session/${sessionId}/normal_smooth`),
    fetchBitmap(`/session/${sessionId}/aux`),
    // Missing on a backend from before this map existed: then one mid-grey pixel, which means "no detail".
    fetchBitmap(`/session/${sessionId}/detail`).catch(() =>
      createImageBitmap(new ImageData(new Uint8ClampedArray([128, 128, 128, 255]), 1, 1), RAW_BITMAP)
    ),
    backendFetch(`/session/${sessionId}/depth_raw`).then((response) => response.arrayBuffer()),
    // Missing on a backend from before this map existed: then everything counts as solid.
    backendFetch(`/session/${sessionId}/thickness_raw`)
      .then((response) => response.arrayBuffer())
      .catch(() => new ArrayBuffer(0))
  ])
  const [width, height] = info.working_size
  const depth = depthFromUint16(new Uint8Array(depthBytes))
  const thickness =
    thicknessBytes.byteLength === width * height ? new Uint8Array(thicknessBytes) : new Uint8Array(width * height)
  return { albedo, normal, normalSmooth, aux, detail, depth, thickness, width, height }
}

/** Counts opens, so a slow earlier open cannot overwrite a newer one. */
let openCounter = 0
let runningJob: string | null = null

export const useSessionStore = create<SessionStore>((set, get) => ({
  status: 'empty',
  progress: 0,
  message: '',
  error: null,
  sourceName: null,
  sessionId: null,
  maps: null,

  open: async (source) => {
    const ticket = ++openCounter
    const current = (): boolean => ticket === openCounter
    get().cancel()
    set({ status: 'working', progress: 0, message: 'Sending image', error: null })

    try {
      const form = new FormData()
      form.append('file', source.data, source.name)
      const session = (await (
        await backendFetch('/session', { method: 'POST', body: form })
      ).json()) as SessionResponse

      if (session.job_id !== null) {
        runningJob = session.job_id
        for await (const event of jobEvents(session.job_id)) {
          if (!current()) return
          if (event.type === 'progress') {
            const download =
              event.download_total_mb !== undefined
                ? ` (${event.download_done_mb} / ${event.download_total_mb} MB)`
                : ''
            set({ progress: event.progress ?? 0, message: `${event.message ?? ''}${download}` })
          } else if (event.type === 'error') {
            throw new Error(event.error ?? 'Preprocess failed')
          } else if (event.type === 'cancelled') {
            // Go back to the picture that was open before, if any.
            set({ status: get().maps ? 'ready' : 'empty', message: '' })
            return
          }
        }
        runningJob = null
      }

      if (!current()) return
      set({ progress: 1, message: 'Loading maps' })
      const maps = await fetchMaps(session.session_id)
      if (!current()) return

      useLightsStore.getState().reset(starterLights())
      set({
        status: 'ready',
        message: '',
        maps,
        sessionId: session.session_id,
        sourceName: source.name
      })
    } catch (error) {
      if (!current()) return
      set({ status: 'error', error: error instanceof Error ? error.message : String(error) })
    }
  },

  cancel: () => {
    if (runningJob === null) return
    void backendFetch(`/jobs/${runningJob}/cancel`, { method: 'POST' }).catch(() => undefined)
    runningJob = null
  }
}))
