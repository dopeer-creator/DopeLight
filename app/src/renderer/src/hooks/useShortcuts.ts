import { useEffect } from 'react'
import { useExportStore } from '../stores/exportStore'
import { useLightsStore } from '../stores/lightsStore'
import { useSessionStore } from '../stores/sessionStore'
import { useViewStore } from '../stores/viewStore'

const NUDGE = 0.005 // of the image size per arrow press
const NUDGE_FAST = 0.02 // with Shift

const ARROWS: Record<string, [number, number]> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1]
}

/** True when the key press belongs to a form control (typing, moving a slider). */
function inControl(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName)
}

/** Keyboard shortcuts: L, Del, C (hold), Ctrl+Z / Ctrl+Y, Ctrl+O, Ctrl+E, Esc, arrow keys. */
export function useShortcuts(onOpen: () => void): void {
  useEffect(() => {
    const down = (event: KeyboardEvent): void => {
      const lights = useLightsStore.getState()
      const key = event.key.toLowerCase()

      if (event.ctrlKey || event.metaKey) {
        if (key === 'o') {
          event.preventDefault()
          onOpen()
        } else if (key === 'e') {
          event.preventDefault()
          useExportStore.getState().show()
        } else if (key === 'z' && !event.shiftKey) {
          event.preventDefault()
          lights.undo()
        } else if (key === 'y' || (key === 'z' && event.shiftKey)) {
          event.preventDefault()
          lights.redo()
        }
        return
      }
      if (key === 'escape') useExportStore.getState().hide()
      // While the export dialog is open, the picture's shortcuts are off.
      if (useExportStore.getState().open) return
      if (inControl(event.target) || useSessionStore.getState().status !== 'ready') return

      if (key === 'c') {
        useViewStore.getState().setComparing(true)
      } else if (key === 'l' && !event.repeat) {
        lights.addLight()
      } else if ((key === 'delete' || key === 'backspace') && lights.selectedId !== null) {
        lights.deleteLight(lights.selectedId)
      } else if (event.key in ARROWS && lights.selectedId !== null) {
        event.preventDefault()
        if (!event.repeat) lights.checkpoint() // holding the key is one undo step
        const [dx, dy] = ARROWS[event.key]!
        const step = event.shiftKey ? NUDGE_FAST : NUDGE
        lights.nudgeLight(lights.selectedId, dx * step, dy * step)
      }
    }

    const up = (event: KeyboardEvent): void => {
      if (event.key.toLowerCase() === 'c') useViewStore.getState().setComparing(false)
    }
    const blur = (): void => useViewStore.getState().setComparing(false)

    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', blur)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', blur)
    }
  }, [onOpen])
}
