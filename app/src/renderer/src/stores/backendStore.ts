import { create } from 'zustand'
import type { BackendInfo, HealthResponse } from '@shared/types'

interface BackendStore {
  info: BackendInfo
  health: HealthResponse | null
  healthError: string | null
  setInfo: (info: BackendInfo) => void
  refreshHealth: () => Promise<void>
}

export const useBackendStore = create<BackendStore>((set, get) => ({
  info: { state: 'starting', baseUrl: null, token: null, error: null },
  health: null,
  healthError: null,

  setInfo: (info) => set(info.state === 'running' ? { info } : { info, health: null }),

  refreshHealth: async () => {
    const { baseUrl, token, state } = get().info
    if (state !== 'running' || baseUrl === null || token === null) return
    try {
      const response = await fetch(`${baseUrl}/health`, {
        headers: { Authorization: `Bearer ${token}` }
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      set({ health: (await response.json()) as HealthResponse, healthError: null })
    } catch (error) {
      set({ health: null, healthError: error instanceof Error ? error.message : String(error) })
    }
  }
}))
