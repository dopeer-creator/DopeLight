export type BackendState = 'starting' | 'running' | 'stopped' | 'error'

export interface BackendInfo {
  state: BackendState
  /** e.g. http://127.0.0.1:51234, null until a port is chosen */
  baseUrl: string | null
  /** per-launch token, sent as `Authorization: Bearer <token>` */
  token: string | null
  error: string | null
}

export interface GpuStatus {
  available: boolean
  name: string | null
  vram_total_mb: number | null
  vram_free_mb: number | null
  source: 'torch' | 'nvidia-smi' | 'none'
}

export interface HealthResponse {
  status: string
  app: string
  version: string
  gpu: GpuStatus
  models: Record<string, boolean>
}

/** POST /session */
export interface SessionResponse {
  session_id: string
  cached: boolean
  job_id: string | null
  maps: Record<string, string>
}

/** GET /session/{id} */
export interface SessionInfo {
  id: string
  source_name: string
  original_size: [number, number]
  working_size: [number, number]
  normals_method: string
}

/** One server-sent event from GET /jobs/{id}/events */
export interface JobEvent {
  type: 'progress' | 'done' | 'error' | 'cancelled' | 'keepalive'
  stage?: string
  progress?: number
  message?: string
  error?: string
  download_done_mb?: number
  download_total_mb?: number
  /** On `done`: what the job returned (an export lists the files it wrote). */
  result?: { files?: string[]; render_id?: string; note?: string; seconds?: number }
}

/** Development helpers (see app/src/main/dev.ts). */
export interface Automation {
  openImage: { name: string; bytes: Uint8Array } | null
  /** JSON text: { lights, globals } */
  scene: string | null
  /** Time the shader at 1080p and 4K once the image is open, and log the result. */
  bench: boolean
}

export interface ParityFixture {
  /** JSON text: { width, height, scenes: [...] } */
  scenes: string
  albedo: Uint8Array
  normal: Uint8Array
  normalSmooth: Uint8Array
  aux: Uint8Array
  /** raw little-endian uint16 */
  depth: Uint8Array
}

/** What the preload script exposes on `window.relight`. */
export interface RelightApi {
  getBackend: () => Promise<BackendInfo>
  /** Returns an unsubscribe function. */
  onBackendChange: (callback: (info: BackendInfo) => void) => () => void
  /** Ask where to save. `extension` without the dot. Resolves to the full path, or null if cancelled. */
  chooseExportPath: (defaultName: string, extension: string) => Promise<string | null>
  /** Open the folder of a file in Explorer, with the file selected. */
  revealFile: (path: string) => void
  dev: {
    automation: () => Promise<Automation>
    /** Tells the main process the opened image is drawn (for screenshots). */
    ready: () => void
    parityLoad: () => Promise<ParityFixture | null>
    parityResult: (name: string, pixels: Uint8Array) => Promise<void>
    parityFinish: (error: string | null) => Promise<void>
  }
}

export const IPC = {
  backendGet: 'backend:get',
  backendChanged: 'backend:changed',
  exportChoosePath: 'export:choosePath',
  exportReveal: 'export:reveal',
  devAutomation: 'dev:automation',
  devReady: 'dev:ready',
  parityLoad: 'parity:load',
  parityResult: 'parity:result',
  parityFinish: 'parity:finish'
} as const
