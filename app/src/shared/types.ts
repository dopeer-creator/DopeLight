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

/** What the preload script exposes on `window.relight`. */
export interface RelightApi {
  getBackend: () => Promise<BackendInfo>
  /** Returns an unsubscribe function. */
  onBackendChange: (callback: (info: BackendInfo) => void) => () => void
}

export const IPC = {
  backendGet: 'backend:get',
  backendChanged: 'backend:changed'
} as const
