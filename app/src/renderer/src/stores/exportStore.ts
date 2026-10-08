import { create } from 'zustand'
import { backendFetch, jobEvents } from '../api'
import { useLightsStore } from './lightsStore'
import { useRenderStore } from './renderStore'
import { useSessionStore } from './sessionStore'

export type ExportKind = 'relit' | 'light_layer' | 'per_light' | 'multiply'
/** Export what the live preview shows, or the last photoreal render. */
export type ExportSource = 'preview' | 'photoreal'
export type ExportFormat = 'png' | 'jpeg' | 'tiff'
export type BlendTarget = 'normal' | 'linear'

export interface ExportOptions {
  source: ExportSource
  kind: ExportKind
  format: ExportFormat
  bitDepth: 8 | 16
  quality: number
  blend: BlendTarget
  alpha: boolean
}

const EXTENSION: Record<ExportFormat, string> = { png: 'png', jpeg: 'jpg', tiff: 'tif' }
const SUFFIX: Record<ExportKind, string> = {
  relit: '_relit',
  light_layer: '_light',
  per_light: '_lights',
  multiply: '_multiply'
}

/** Kinds each source can produce. */
export const KINDS_FOR: Record<ExportSource, ExportKind[]> = {
  preview: ['relit', 'light_layer', 'per_light'],
  photoreal: ['relit', 'light_layer', 'multiply']
}

interface ExportStore {
  open: boolean
  options: ExportOptions
  running: boolean
  progress: number
  message: string
  /** Files written by the last export. */
  files: string[]
  error: string | null
  show: () => void
  hide: () => void
  setOptions: (patch: Partial<ExportOptions>) => void
  run: () => Promise<void>
  cancel: () => void
}

let runningJob: string | null = null

/** "holiday.photo.jpg" -> "holiday.photo" */
function stem(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(0, dot) : name
}

export const useExportStore = create<ExportStore>((set, get) => ({
  open: false,
  options: {
    source: 'preview',
    kind: 'relit',
    format: 'png',
    bitDepth: 8,
    quality: 92,
    blend: 'normal',
    alpha: false
  },
  running: false,
  progress: 0,
  message: '',
  files: [],
  error: null,

  show: () => {
    if (useSessionStore.getState().status !== 'ready') return
    // Start from what the picture is showing right now.
    const source: ExportSource = useRenderStore.getState().showing ? 'photoreal' : 'preview'
    set({ open: true, error: null, files: [] })
    get().setOptions({ source })
  },
  hide: () => {
    if (!get().running) set({ open: false })
  },
  setOptions: (patch) =>
    set((state) => {
      const options = { ...state.options, ...patch }
      // A kind the chosen source cannot make falls back to the relit image.
      if (!KINDS_FOR[options.source].includes(options.kind)) options.kind = 'relit'
      return { options }
    }),

  run: async () => {
    const { options, running } = get()
    const { sessionId, sourceName } = useSessionStore.getState()
    if (running || sessionId === null) return

    // The original keeps its name; the export gets a suffix.
    const renderId = options.source === 'photoreal' ? useRenderStore.getState().renderId : null
    const tag = renderId !== null ? '_photoreal' : ''
    const defaultName = `${stem(sourceName ?? 'image')}${tag}${SUFFIX[options.kind]}.${EXTENSION[options.format]}`
    const target = await window.relight.chooseExportPath(defaultName, EXTENSION[options.format])
    if (target === null) return

    set({ running: true, progress: 0, message: 'Starting', error: null, files: [] })
    try {
      const { lights, globals } = useLightsStore.getState()
      const response = await backendFetch(`/session/${sessionId}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          lights,
          globals,
          kind: options.kind,
          format: options.format,
          bit_depth: options.bitDepth,
          quality: options.quality,
          blend: options.blend,
          alpha: options.alpha,
          render_id: renderId,
          target
        })
      })
      const { job_id: jobId } = (await response.json()) as { job_id: string }
      runningJob = jobId
      for await (const event of jobEvents(jobId)) {
        if (event.type === 'progress') {
          set({ progress: event.progress ?? 0, message: event.message ?? '' })
        } else if (event.type === 'error') {
          throw new Error(event.error ?? 'Export failed')
        } else if (event.type === 'cancelled') {
          set({ message: 'Cancelled' })
        } else if (event.type === 'done') {
          set({ files: event.result?.files ?? [], message: '' })
        }
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
  }
}))
