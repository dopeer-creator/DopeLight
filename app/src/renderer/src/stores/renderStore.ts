import { create } from 'zustand'
import { backendFetch, jobEvents } from '../api'
import { useLightsStore } from './lightsStore'
import { useSessionStore } from './sessionStore'

/** The photoreal pass: settings, the running job, and the last result. */

export interface RenderOptions {
  prompt: string
  /** 0..1: how closely the result follows where the lights are placed. */
  adherence: number
  steps: number
  seed: number
  /** Second, larger pass for more detail (slower, needs more memory). */
  highres: boolean
}

interface RenderStore {
  open: boolean
  options: RenderOptions
  running: boolean
  progress: number
  message: string
  error: string | null
  /** The last finished render of the open image. */
  renderId: string | null
  imageUrl: string | null
  note: string
  seconds: number | null
  /** True while the picture shows the render instead of the live preview. */
  showing: boolean
  /** True once the lights changed after the render was made. */
  outdated: boolean
  show: () => void
  hide: () => void
  setOptions: (patch: Partial<RenderOptions>) => void
  setShowing: (showing: boolean) => void
  run: () => Promise<void>
  cancel: () => void
  /** Forget the result (a new image was opened). */
  clear: () => void
}

let runningJob: string | null = null

export const useRenderStore = create<RenderStore>((set, get) => ({
  open: false,
  options: { prompt: 'beautiful lighting, natural', adherence: 0.5, steps: 25, seed: 12345, highres: true },
  running: false,
  progress: 0,
  message: '',
  error: null,
  renderId: null,
  imageUrl: null,
  note: '',
  seconds: null,
  showing: false,
  outdated: false,

  show: () => {
    if (useSessionStore.getState().status === 'ready') set({ open: true, error: null })
  },
  hide: () => {
    if (!get().running) set({ open: false })
  },
  setOptions: (patch) => set((state) => ({ options: { ...state.options, ...patch } })),
  setShowing: (showing) => set({ showing: showing && get().imageUrl !== null }),

  run: async () => {
    const { options, running } = get()
    const sessionId = useSessionStore.getState().sessionId
    if (running || sessionId === null) return
    set({ running: true, progress: 0, message: 'Starting', error: null })
    try {
      const { lights, globals } = useLightsStore.getState()
      const response = await backendFetch(`/session/${sessionId}/render`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lights, globals, ...options })
      })
      const { job_id: jobId } = (await response.json()) as { job_id: string }
      runningJob = jobId
      let renderId: string | null = null
      for await (const event of jobEvents(jobId)) {
        if (event.type === 'progress') {
          const total = event.download_total_mb
          if (total !== undefined && total > 0) {
            // A model download: the bar shows the download itself, which can take a while.
            const done = event.download_done_mb ?? 0
            set({
              progress: done / total,
              message: `${event.message ?? 'Downloading'}: ${done} of ${total} MB. This happens once; later renders start straight away.`
            })
          } else {
            set({ progress: event.progress ?? 0, message: event.message ?? '' })
          }
        } else if (event.type === 'error') {
          throw new Error(event.error ?? 'Render failed')
        } else if (event.type === 'cancelled') {
          set({ message: 'Cancelled' })
        } else if (event.type === 'done') {
          renderId = event.result?.render_id ?? null
          set({ note: event.result?.note ?? '', seconds: event.result?.seconds ?? null })
        }
      }
      if (renderId !== null && useSessionStore.getState().sessionId === sessionId) {
        const picture = await backendFetch(`/session/${sessionId}/render/${renderId}`)
        const previous = get().imageUrl
        set({
          renderId,
          imageUrl: URL.createObjectURL(await picture.blob()),
          showing: true,
          outdated: false,
          open: false,
          message: ''
        })
        if (previous !== null) URL.revokeObjectURL(previous)
      }
    } catch (error) {
      set({ error: error instanceof Error ? error.message : String(error) })
    } finally {
      runningJob = null
      set({ running: false })
    }
  },

  cancel: () => {
    if (runningJob !== null) {
      void backendFetch(`/jobs/${runningJob}/cancel`, { method: 'POST' }).catch(() => undefined)
    }
  },

  clear: () => {
    const previous = get().imageUrl
    if (previous !== null) URL.revokeObjectURL(previous)
    set({ renderId: null, imageUrl: null, showing: false, outdated: false, note: '', seconds: null })
  }
}))

// Moving a light makes the render out of date: go back to the live preview.
useLightsStore.subscribe((state, previous) => {
  if (state.lights === previous.lights && state.globals === previous.globals) return
  const render = useRenderStore.getState()
  if (render.imageUrl !== null && !render.outdated) {
    useRenderStore.setState({ outdated: true, showing: false })
  }
})

// A different image has no render yet.
useSessionStore.subscribe((state, previous) => {
  if (state.sessionId !== previous.sessionId) useRenderStore.getState().clear()
})
