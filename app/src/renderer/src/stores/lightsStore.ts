import { create } from 'zustand'
import {
  clamp,
  createLight,
  DEFAULT_GLOBALS,
  type GlobalSettings,
  type Light,
  MAX_LIGHTS,
  RANGES
} from '@shared/lighting'

/** What undo/redo restores. */
interface Snapshot {
  lights: Light[]
  globals: GlobalSettings
  selectedId: string | null
}

const HISTORY_LIMIT = 100

interface LightsStore extends Snapshot {
  past: Snapshot[]
  future: Snapshot[]

  /**
   * Save the current state as an undo step. Call once at the START of a change
   * (pointer down on a slider or gizmo, or right before a button's action), so
   * a whole drag is one step.
   */
  checkpoint: () => void
  undo: () => void
  redo: () => void

  addLight: () => void
  duplicateLight: (id: string) => void
  deleteLight: (id: string) => void
  /** Move a light one place up (-1) or down (+1) in the list. */
  moveLight: (id: string, offset: -1 | 1) => void
  select: (id: string | null) => void
  updateLight: (id: string, patch: Partial<Light>) => void
  /** Move by a delta in normalized image coords, kept inside the allowed area. */
  nudgeLight: (id: string, dx: number, dy: number) => void
  updateGlobals: (patch: Partial<GlobalSettings>) => void
  /** Start over (new image): given lights, no history. */
  reset: (lights?: Light[], globals?: GlobalSettings) => void
}

const newId = (): string => crypto.randomUUID()

const snapshot = (state: Snapshot): Snapshot => ({
  lights: state.lights,
  globals: state.globals,
  selectedId: state.selectedId
})

export const useLightsStore = create<LightsStore>((set, get) => ({
  lights: [],
  globals: DEFAULT_GLOBALS,
  selectedId: null,
  past: [],
  future: [],

  checkpoint: () =>
    set((state) => ({ past: [...state.past, snapshot(state)].slice(-HISTORY_LIMIT), future: [] })),

  undo: () =>
    set((state) => {
      const previous = state.past.at(-1)
      if (!previous) return state
      return { ...previous, past: state.past.slice(0, -1), future: [snapshot(state), ...state.future] }
    }),

  redo: () =>
    set((state) => {
      const next = state.future[0]
      if (!next) return state
      return { ...next, past: [...state.past, snapshot(state)], future: state.future.slice(1) }
    }),

  addLight: () => {
    const { lights, checkpoint } = get()
    if (lights.length >= MAX_LIGHTS) return
    checkpoint()
    const light = createLight(newId(), lights.length)
    set({ lights: [...lights, light], selectedId: light.id })
  },

  duplicateLight: (id) => {
    const { lights, checkpoint } = get()
    const source = lights.find((light) => light.id === id)
    if (!source || lights.length >= MAX_LIGHTS) return
    checkpoint()
    const { min, max } = RANGES.position
    const copy: Light = {
      ...source,
      id: newId(),
      name: `${source.name} copy`,
      position: {
        ...source.position,
        x: clamp(source.position.x + 0.06, min, max),
        y: clamp(source.position.y + 0.06, min, max)
      }
    }
    set({ lights: [...lights, copy], selectedId: copy.id })
  },

  deleteLight: (id) => {
    const { lights, selectedId, checkpoint } = get()
    if (!lights.some((light) => light.id === id)) return
    checkpoint()
    const remaining = lights.filter((light) => light.id !== id)
    set({
      lights: remaining,
      selectedId: selectedId === id ? (remaining.at(-1)?.id ?? null) : selectedId
    })
  },

  moveLight: (id, offset) => {
    const { lights, checkpoint } = get()
    const from = lights.findIndex((light) => light.id === id)
    const to = from + offset
    if (from === -1 || to < 0 || to >= lights.length) return
    checkpoint()
    const reordered = [...lights]
    const [moved] = reordered.splice(from, 1)
    reordered.splice(to, 0, moved!)
    set({ lights: reordered })
  },

  select: (id) => set({ selectedId: id }),

  updateLight: (id, patch) =>
    set((state) => ({
      lights: state.lights.map((light) => (light.id === id ? { ...light, ...patch } : light))
    })),

  nudgeLight: (id, dx, dy) => {
    const light = get().lights.find((entry) => entry.id === id)
    if (!light) return
    const { min, max } = RANGES.position
    get().updateLight(id, {
      position: {
        ...light.position,
        x: clamp(light.position.x + dx, min, max),
        y: clamp(light.position.y + dy, min, max)
      }
    })
  },

  updateGlobals: (patch) => set((state) => ({ globals: { ...state.globals, ...patch } })),

  reset: (lights = [], globals = DEFAULT_GLOBALS) =>
    set({ lights, globals, selectedId: lights[0]?.id ?? null, past: [], future: [] })
}))

/** A first light for a freshly opened image, so the effect is visible at once. */
export function starterLights(): Light[] {
  return [createLight(newId(), 0)]
}
