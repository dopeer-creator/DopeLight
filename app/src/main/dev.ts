import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { basename, join } from 'node:path'
import { app, type BrowserWindow, ipcMain } from 'electron'
import { type Automation, IPC, type ParityFixture } from '@shared/types'
import { log } from './logger'

/**
 * Development-only helpers, driven by environment variables. None of them do
 * anything in a packaged app.
 *
 *   RELIGHT_SCREENSHOT=<file.png>  save a capture 6 s after each page load,
 *                                  or as soon as the renderer says it is ready
 *   RELIGHT_OPEN=<image>           open this image on start
 *   RELIGHT_SCENE=<file.json>      lights/globals to load once the image is ready
 *   RELIGHT_BENCH=1                time the shader at 1080p and 4K with that image and
 *                                  scene; the result goes to the log as "BENCH ..."
 *   RELIGHT_SCRIPT=<file.js>       run this JavaScript in the page once the image is drawn
 *   RELIGHT_SCRIPT_OUT=<file.json> write the script's result here, then quit
 *   RELIGHT_EXPORT_DIR=<folder>    exports save here without showing the save dialog
 *   RELIGHT_PARITY=<folder>        render the folder's fixture with the real
 *                                  shader, write the pixels there, and quit
 */

const env = (name: string): string | undefined => (app.isPackaged ? undefined : process.env[name])

export function exportFolder(): string | undefined {
  return env('RELIGHT_EXPORT_DIR')
}

export function parityFolder(): string | undefined {
  return env('RELIGHT_PARITY')
}

function automation(): Automation {
  const image = env('RELIGHT_OPEN')
  const scene = env('RELIGHT_SCENE')
  return {
    openImage:
      image && existsSync(image) ? { name: basename(image), bytes: readFileSync(image) } : null,
    scene: scene && existsSync(scene) ? readFileSync(scene, 'utf8') : null,
    bench: env('RELIGHT_BENCH') === '1'
  }
}

function capture(window: BrowserWindow, target: string): void {
  // A covered window or a sleeping display stops painting, and the capture would
  // be an old frame. Ask for a fresh one first.
  window.webContents.setBackgroundThrottling(false)
  window.webContents.invalidate()
  void window.webContents.capturePage().then((image) => {
    writeFileSync(target, image.toPNG())
    log('INFO', 'main', `screenshot saved to ${target}`)
  })
}

export function registerDevHandlers(): void {
  ipcMain.handle(IPC.devAutomation, () => automation())

  const folder = parityFolder()
  ipcMain.handle(IPC.parityLoad, (): ParityFixture | null => {
    if (!folder) return null
    return {
      scenes: readFileSync(join(folder, 'scenes.json'), 'utf8'),
      albedo: readFileSync(join(folder, 'albedo.png')),
      normal: readFileSync(join(folder, 'normal.png')),
      normalSmooth: readFileSync(join(folder, 'normal_smooth.png')),
      aux: readFileSync(join(folder, 'aux.png')),
      depth: readFileSync(join(folder, 'depth.raw'))
    }
  })
  ipcMain.handle(IPC.parityResult, (_event, name: string, pixels: Uint8Array) => {
    if (folder) writeFileSync(join(folder, `gl_${name}.rgba`), pixels)
  })
  ipcMain.handle(IPC.parityFinish, (_event, error: string | null) => {
    if (!folder) return
    writeFileSync(join(folder, 'gl_status.json'), JSON.stringify({ ok: error === null, error }))
    app.quit()
  })
}

/** Run the RELIGHT_SCRIPT file in the page and save what it returns. */
async function runScript(window: BrowserWindow, file: string): Promise<void> {
  let result: unknown
  try {
    result = await window.webContents.executeJavaScript(readFileSync(file, 'utf8'), true)
  } catch (error) {
    result = { error: error instanceof Error ? error.message : String(error) }
  }
  const out = env('RELIGHT_SCRIPT_OUT')
  if (out) {
    writeFileSync(out, JSON.stringify(result, null, 2))
    app.quit()
  } else {
    log('INFO', 'main', `script result: ${JSON.stringify(result)}`)
  }
}

export function attachDevHelpers(window: BrowserWindow): void {
  const target = env('RELIGHT_SCREENSHOT')
  const script = env('RELIGHT_SCRIPT')
  // With an image to open, wait for the renderer to say the picture is drawn.
  if (env('RELIGHT_OPEN')) {
    ipcMain.on(IPC.devReady, () => {
      if (script && existsSync(script)) void runScript(window, script)
      // 1.5 s: long enough for the frame-time readout in the status bar to appear.
      if (target) setTimeout(() => capture(window, target), 1500)
    })
  } else if (target) {
    window.webContents.on('did-finish-load', () => setTimeout(() => capture(window, target), 6000))
  }
}
