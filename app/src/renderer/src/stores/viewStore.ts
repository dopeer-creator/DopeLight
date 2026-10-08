import { create } from 'zustand'

interface ViewStore {
  /** True while the user holds Compare: show the original. */
  comparing: boolean
  /** Split view: original on the left of `splitAt`, relit on the right. */
  split: boolean
  splitAt: number
  /** Time the GPU took for the last measured frame, in ms (null = not measured). */
  frameMs: number | null
  setComparing: (comparing: boolean) => void
  toggleSplit: () => void
  setSplitAt: (splitAt: number) => void
  setFrameMs: (frameMs: number | null) => void
}

export const useViewStore = create<ViewStore>((set) => ({
  comparing: false,
  split: false,
  splitAt: 0.5,
  frameMs: null,
  setComparing: (comparing) => set({ comparing }),
  toggleSplit: () => set((state) => ({ split: !state.split })),
  setSplitAt: (splitAt) => set({ splitAt: Math.min(1, Math.max(0, splitAt)) }),
  setFrameMs: (frameMs) => set({ frameMs })
}))
