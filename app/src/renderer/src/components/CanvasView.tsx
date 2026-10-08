import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { clamp, type Light, linearToHex, RANGES } from '@shared/lighting'
import { RelightRenderer, surfaceHeightAt } from '../gl/renderer'
import { useLightsStore } from '../stores/lightsStore'
import { useSessionStore } from '../stores/sessionStore'
import { useViewStore } from '../stores/viewStore'

const PADDING = 24 // px kept free around the picture
const WHEEL_Z_PER_PIXEL = 0.0008
const WHEEL_BURST_MS = 400 // wheel ticks closer than this are one undo step
const SHARPEN_AFTER_IDLE_MS = 250
const MEASURE_FRAMES = 2
const FRAME_BUDGET_MS = 14 // just under 60 frames per second
const MIN_DRAG_SCALE = 0.4
const STEM_PX_PER_UNIT = 36 // length of the height line under a light, per unit of z

interface Size {
  width: number
  height: number
}

/** Largest size with the image's shape that fits the container. */
function fitInside(container: Size, image: Size): Size {
  const available = { width: container.width - PADDING * 2, height: container.height - PADDING * 2 }
  if (available.width <= 0 || available.height <= 0) return { width: 0, height: 0 }
  const scale = Math.min(available.width / image.width, available.height / image.height)
  return { width: Math.floor(image.width * scale), height: Math.floor(image.height * scale) }
}

export function CanvasView(): React.JSX.Element {
  const maps = useSessionStore((store) => store.maps)
  const lights = useLightsStore((store) => store.lights)
  const selectedId = useLightsStore((store) => store.selectedId)
  const split = useViewStore((store) => store.split)
  const splitAt = useViewStore((store) => store.splitAt)

  const containerRef = useRef<HTMLDivElement>(null)
  const overlayRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rendererRef = useRef<RelightRenderer | null>(null)
  const frameRef = useRef(0)
  const idleTimer = useRef(0)
  /** Canvas pixel size at full quality. */
  const fullSize = useRef<Size>({ width: 0, height: 0 })
  /** Resolution factor used while dragging; below 1 when full quality is too slow. */
  const dragScale = useRef(1)
  const wheelTimer = useRef(0)
  const [container, setContainer] = useState<Size>({ width: 0, height: 0 })
  const [glError, setGlError] = useState<string | null>(null)

  const size = maps ? fitInside(container, maps) : { width: 0, height: 0 }

  // --- drawing -------------------------------------------------------------

  const draw = useCallback((scale = 1) => {
    const renderer = rendererRef.current
    const canvas = canvasRef.current
    if (!renderer || !canvas || fullSize.current.width === 0) return
    // Resizing clears the canvas, so only do it when the size really changes,
    // and always draw right after.
    const width = Math.max(1, Math.round(fullSize.current.width * scale))
    const height = Math.max(1, Math.round(fullSize.current.height * scale))
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width
      canvas.height = height
    }
    const { lights, globals } = useLightsStore.getState()
    const view = useViewStore.getState()
    renderer.draw({
      lights,
      globals,
      mode: view.comparing ? 'original' : 'relit',
      split: view.split ? view.splitAt : null
    })
  }, [])

  /**
   * Once things are quiet: draw at full quality and time it. If a full-quality
   * frame is slower than the budget, later drags render at a lower resolution
   * (the proxy) so they stay smooth, and this sharpens the picture again.
   */
  const sharpenSoon = useCallback(() => {
    window.clearTimeout(idleTimer.current)
    idleTimer.current = window.setTimeout(() => {
      const renderer = rendererRef.current
      if (!renderer || !useSessionStore.getState().maps) return
      draw()
      renderer.finish()
      const start = performance.now()
      for (let i = 0; i < MEASURE_FRAMES; i++) {
        draw()
        renderer.finish()
      }
      const frameMs = (performance.now() - start) / MEASURE_FRAMES
      // Cost grows with the pixel count, so scale each side by the square root.
      dragScale.current = clamp(Math.sqrt(FRAME_BUDGET_MS / frameMs), MIN_DRAG_SCALE, 1)
      useViewStore.getState().setFrameMs(frameMs)
    }, SHARPEN_AFTER_IDLE_MS)
  }, [draw])

  /** Redraw on the next animation frame; many changes in one frame draw once. */
  const schedule = useCallback(() => {
    if (frameRef.current !== 0) return
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = 0
      draw(dragScale.current)
      sharpenSoon()
    })
  }, [draw, sharpenSoon])

  useEffect(() => {
    try {
      rendererRef.current = new RelightRenderer(canvasRef.current!)
    } catch (error) {
      setGlError(error instanceof Error ? error.message : String(error))
    }
    return () => {
      rendererRef.current?.dispose()
      rendererRef.current = null
    }
  }, [])

  // Sliders and dragging only change store values; redraw whenever they do.
  useEffect(() => {
    const stopLights = useLightsStore.subscribe((state, previous) => {
      if (state.lights !== previous.lights || state.globals !== previous.globals) schedule()
    })
    const stopView = useViewStore.subscribe((state, previous) => {
      if (
        state.comparing !== previous.comparing ||
        state.split !== previous.split ||
        state.splitAt !== previous.splitAt
      ) {
        schedule()
      }
    })
    return () => {
      stopLights()
      stopView()
    }
  }, [schedule])

  useEffect(() => {
    if (maps && rendererRef.current) {
      rendererRef.current.setMaps(maps)
      schedule()
    }
  }, [maps, schedule])

  // Render at the size the picture is shown at (times the display's pixel ratio).
  useLayoutEffect(() => {
    if (size.width === 0) return
    const ratio = window.devicePixelRatio || 1
    fullSize.current = {
      width: Math.round(size.width * ratio),
      height: Math.round(size.height * ratio)
    }
    draw()
    sharpenSoon()
  }, [size.width, size.height, draw, sharpenSoon])

  useEffect(() => {
    const element = containerRef.current!
    const observer = new ResizeObserver(([entry]) => {
      const rect = entry!.contentRect
      setContainer({ width: rect.width, height: rect.height })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  // --- interaction -----------------------------------------------------------

  /** Follow the pointer until release, reporting normalized image coords. */
  const drag = (
    event: React.PointerEvent,
    origin: { x: number; y: number } | null,
    apply: (x: number, y: number) => void
  ): void => {
    event.preventDefault()
    event.stopPropagation()
    const rect = overlayRef.current!.getBoundingClientRect()
    const toImage = (e: { clientX: number; clientY: number }): { x: number; y: number } => ({
      x: (e.clientX - rect.left) / rect.width,
      y: (e.clientY - rect.top) / rect.height
    })
    // Keep the grab point under the cursor instead of snapping the centre to it.
    const start = toImage(event)
    const offset = origin ? { x: origin.x - start.x, y: origin.y - start.y } : { x: 0, y: 0 }
    const move = (e: PointerEvent): void => {
      const point = toImage(e)
      apply(point.x + offset.x, point.y + offset.y)
    }
    const stop = (): void => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
  }

  const store = useLightsStore.getState
  const { min, max } = RANGES.position

  const dragLight = (event: React.PointerEvent, light: Light): void => {
    store().select(light.id)
    store().checkpoint()
    drag(event, light.position, (x, y) =>
      store().updateLight(light.id, {
        position: { ...light.position, x: clamp(x, min, max), y: clamp(y, min, max) }
      })
    )
  }

  const dragTarget = (event: React.PointerEvent, light: Light): void => {
    store().select(light.id)
    store().checkpoint()
    drag(event, light.target, (x, y) =>
      store().updateLight(light.id, { target: { x: clamp(x, min, max), y: clamp(y, min, max) } })
    )
  }

  const dragSplit = (event: React.PointerEvent): void => {
    drag(event, null, (x) => useViewStore.getState().setSplitAt(x))
  }

  /** Mouse wheel changes the selected light's height. */
  const onWheel = (event: React.WheelEvent): void => {
    const { selectedId, lights, checkpoint, updateLight } = store()
    const light = lights.find((entry) => entry.id === selectedId)
    if (!light) return
    if (wheelTimer.current === 0) checkpoint()
    window.clearTimeout(wheelTimer.current)
    wheelTimer.current = window.setTimeout(() => (wheelTimer.current = 0), WHEEL_BURST_MS)
    const z = clamp(light.position.z - event.deltaY * WHEEL_Z_PER_PIXEL, RANGES.z.min, RANGES.z.max)
    updateLight(light.id, { position: { ...light.position, z } })
  }

  const percent = (value: number): string => `${value * 100}%`

  return (
    <div className="canvas-area" ref={containerRef}>
      <div
        className="stage"
        style={{ width: size.width, height: size.height, visibility: maps ? 'visible' : 'hidden' }}
      >
        <canvas ref={canvasRef} className="stage-canvas" />
        <div
          className="stage-overlay"
          ref={overlayRef}
          onWheel={onWheel}
          onPointerDown={() => store().select(null)}
        >
          {split && (
            <div className="split-line" style={{ left: percent(splitAt) }} onPointerDown={dragSplit}>
              <span className="split-grip" />
            </div>
          )}

          {lights.map((light) => {
            const selected = light.id === selectedId
            const color = linearToHex(light.color)
            const aims = light.type !== 'point'
            // Lower than the photo's surface at this spot: the light is behind it.
            const behind =
              maps !== null &&
              light.position.z < surfaceHeightAt(maps, light.position.x, light.position.y)
            return (
              <div key={light.id} className={light.enabled ? '' : 'gizmo--off'}>
                {aims && selected && (
                  <>
                    <svg className="aim-line">
                      <line
                        x1={percent(light.position.x)}
                        y1={percent(light.position.y)}
                        x2={percent(light.target.x)}
                        y2={percent(light.target.y)}
                        stroke={color}
                      />
                    </svg>
                    <div
                      className="aim-target"
                      title="Where this light aims. Drag to move."
                      style={{
                        left: percent(light.target.x),
                        top: percent(light.target.y),
                        borderColor: color
                      }}
                      onPointerDown={(event) => dragTarget(event, light)}
                    />
                  </>
                )}
                <div
                  className={`gizmo ${selected ? 'gizmo--selected' : ''} ${behind ? 'gizmo--behind' : ''}`}
                  title={`${light.name}: drag to move, mouse wheel for depth. ${
                    behind ? 'Now BEHIND the surface under it.' : 'Now in front of the surface under it.'
                  }`}
                  style={{
                    left: percent(light.position.x),
                    top: percent(light.position.y),
                    color
                  }}
                  onPointerDown={(event) => dragLight(event, light)}
                >
                  <span className="gizmo-dot" />
                  {/* Faint line down to the image plane: longer = higher above it. */}
                  <span
                    className="gizmo-stem"
                    style={{ height: light.position.z * STEM_PX_PER_UNIT }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {glError !== null && <div className="canvas-message canvas-message--error">{glError}</div>}
    </div>
  )
}
