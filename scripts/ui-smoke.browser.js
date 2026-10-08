// Runs INSIDE the app page (see scripts/ui-smoke.mjs). Acts like a user: real
// pointer, wheel, and keyboard events on the real elements, then checks the
// app's state. Returns { checks: [{ name, ok, detail }] }.
;(async () => {
  const { lights, view } = window.__relight
  const checks = []
  const check = (name, ok, detail = '') => checks.push({ name, ok: Boolean(ok), detail: String(detail) })
  const frame = () => new Promise((resolve) => requestAnimationFrame(() => resolve()))
  const close = (a, b, tolerance = 0.003) => Math.abs(a - b) <= tolerance

  const key = (type, key, options = {}) =>
    window.dispatchEvent(new KeyboardEvent(type, { key, bubbles: true, cancelable: true, ...options }))
  const press = (name, options) => {
    key('keydown', name, options)
    key('keyup', name, options)
  }
  const pointer = (target, type, x, y) =>
    target.dispatchEvent(
      new PointerEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, pointerId: 1, button: 0 })
    )
  const overlay = document.querySelector('.stage-overlay')
  const box = overlay.getBoundingClientRect()
  const selected = () => lights.getState().lights.find((l) => l.id === lights.getState().selectedId)

  // --- start: one starter light ---------------------------------------------
  check('opens with one light', lights.getState().lights.length === 1)
  const canvas = document.querySelector('.stage-canvas')
  check('canvas has pixels', canvas.width > 100 && canvas.height > 100, `${canvas.width}x${canvas.height}`)

  // --- drag the gizmo ---------------------------------------------------------
  const before = { ...selected().position }
  const gizmo = document.querySelector('.gizmo')
  const start = { x: box.left + before.x * box.width, y: box.top + before.y * box.height }
  pointer(gizmo, 'pointerdown', start.x, start.y)
  pointer(window, 'pointermove', start.x + 60, start.y + 30)
  pointer(window, 'pointermove', start.x + 120, start.y + 40)
  pointer(window, 'pointerup', start.x + 120, start.y + 40)
  await frame()
  const dragged = { ...selected().position }
  check(
    'dragging moves the light by the pointer distance',
    close(dragged.x, before.x + 120 / box.width) && close(dragged.y, before.y + 40 / box.height),
    `${before.x.toFixed(3)},${before.y.toFixed(3)} -> ${dragged.x.toFixed(3)},${dragged.y.toFixed(3)}`
  )
  check('dragging keeps the height', dragged.z === before.z)

  // --- undo / redo: the whole drag is one step ---------------------------------
  press('z', { ctrlKey: true })
  check('Ctrl+Z undoes the whole drag', close(selected().position.x, before.x, 1e-9))
  press('y', { ctrlKey: true })
  check('Ctrl+Y redoes it', close(selected().position.x, dragged.x, 1e-9))

  // --- arrow keys nudge ----------------------------------------------------------
  press('ArrowRight')
  check('arrow key nudges right', close(selected().position.x, dragged.x + 0.005, 1e-6))
  press('ArrowUp', { shiftKey: true })
  check('Shift+arrow nudges further', close(selected().position.y, dragged.y - 0.02, 1e-6))

  // --- mouse wheel changes height --------------------------------------------------
  overlay.dispatchEvent(new WheelEvent('wheel', { bubbles: true, deltaY: -100 }))
  check('wheel up raises the light', selected().position.z > dragged.z, selected().position.z.toFixed(3))

  // --- slider -----------------------------------------------------------------------
  const slider = document.querySelector('.panel-section input[type="range"]') // Intensity
  const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
  pointer(slider, 'pointerdown', 0, 0)
  setValue.call(slider, '3.25')
  slider.dispatchEvent(new Event('input', { bubbles: true }))
  await frame()
  check('slider changes intensity', selected().intensity === 3.25, selected().intensity)
  press('z', { ctrlKey: true })
  check('slider change is one undo step', selected().intensity === 1.5, selected().intensity)

  // --- light type buttons ---------------------------------------------------------------
  ;[...document.querySelectorAll('.segmented button')].find((b) => b.textContent === 'Spot').click()
  await frame()
  check('Spot button switches the type', selected().type === 'spot')
  check('spot shows an aim target', document.querySelector('.aim-target') !== null)

  // --- add, limit, delete ------------------------------------------------------------------
  press('l')
  check('L adds a light and selects it', lights.getState().lights.length === 2 && selected().name === 'Light 2')
  for (let i = 0; i < 10; i++) press('l')
  check('never more than 8 lights', lights.getState().lights.length === 8, lights.getState().lights.length)
  await frame()
  check('one gizmo per light', document.querySelectorAll('.gizmo').length === 8)
  press('Delete')
  check('Delete removes the selected light', lights.getState().lights.length === 7)
  press('z', { ctrlKey: true })
  check('undo brings it back', lights.getState().lights.length === 8)

  // --- compare and split --------------------------------------------------------------------
  key('keydown', 'c')
  check('holding C shows the original', view.getState().comparing === true)
  key('keyup', 'c')
  check('releasing C goes back', view.getState().comparing === false)
  ;[...document.querySelectorAll('.toolbar .button')].find((b) => b.textContent.includes('Split')).click()
  await frame()
  check('Split button turns split view on', view.getState().split === true && document.querySelector('.split-line') !== null)

  // --- the picture really changes with the light ----------------------------------------------
  // Compare the canvas with the light on and off. A WebGL canvas only holds its
  // picture until the frame is shown, so read it in the same animation frame as
  // the app's own redraw (ours runs right after it).
  const snap = () => new Promise((resolve) => requestAnimationFrame(() => resolve(canvas.toDataURL())))
  view.setState({ split: false })
  lights.getState().reset([{ ...lights.getState().lights[0], type: 'point', intensity: 3 }])
  const lit = await snap()
  lights.getState().updateLight(lights.getState().lights[0].id, { enabled: false })
  const unlit = await snap()
  check('turning the light off changes the picture', lit !== unlit && lit.length > 5000)

  return { checks }
})()
