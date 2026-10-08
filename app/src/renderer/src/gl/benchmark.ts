import { useLightsStore } from '../stores/lightsStore'
import { useSessionStore } from '../stores/sessionStore'
import { RelightRenderer } from './renderer'

/**
 * Development helper (RELIGHT_BENCH=1): time the shader with the open image
 * and the current lights at fixed output sizes, off screen, and log the result.
 * Warnings from the renderer end up in the main process log.
 */

const SIZES: [string, number, number][] = [
  ['1080p', 1920, 1080],
  ['4K', 3840, 2160]
]
const WARMUP_FRAMES = 3
const TIMED_FRAMES = 20

export function benchmarkShader(): void {
  const maps = useSessionStore.getState().maps
  if (!maps) return
  const { lights, globals } = useLightsStore.getState()
  const active = lights.filter((light) => light.enabled)
  const shadowed = active.filter((light) => light.castShadows).length

  for (const [label, width, height] of SIZES) {
    const renderer = new RelightRenderer(new OffscreenCanvas(width, height))
    renderer.setMaps(maps)
    const frame = (): void => {
      renderer.draw({ lights, globals, mode: 'relit', split: null })
      renderer.finish()
    }
    for (let i = 0; i < WARMUP_FRAMES; i++) frame()
    const start = performance.now()
    for (let i = 0; i < TIMED_FRAMES; i++) frame()
    const ms = (performance.now() - start) / TIMED_FRAMES
    renderer.dispose()
    console.warn(
      `BENCH ${label} ${width}x${height}: ${ms.toFixed(1)} ms per frame (${(1000 / ms).toFixed(0)} fps), ` +
        `${active.length} lights, ${shadowed} with shadows`
    )
  }
}
