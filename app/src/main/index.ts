import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { app, BrowserWindow, ipcMain, shell } from 'electron'
import { APP_NAME } from '@shared/constants'
import { IPC } from '@shared/types'
import { BackendProcess } from './backend'
import { log } from './logger'

app.setName(APP_NAME)

const backend = new BackendProcess()

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 600,
    show: false,
    title: APP_NAME,
    backgroundColor: '#0d0e12',
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false
    }
  })

  window.once('ready-to-show', () => window.show())

  // Links never open inside the app window.
  window.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url)
    return { action: 'deny' }
  })

  window.webContents.on('console-message', (event) => {
    if (event.level === 'warning' || event.level === 'error') {
      log(event.level === 'error' ? 'ERROR' : 'WARNING', 'renderer', event.message)
    }
  })

  const devUrl = process.env['ELECTRON_RENDERER_URL']
  if (!app.isPackaged && devUrl) void window.loadURL(devUrl)
  else void window.loadFile(join(__dirname, '../renderer/index.html'))

  return window
}

/** Dev helper: RELIGHT_SCREENSHOT=<file.png> saves a capture a few seconds after each page load. */
function scheduleScreenshot(window: BrowserWindow): void {
  const target = process.env['RELIGHT_SCREENSHOT']
  if (!target || app.isPackaged) return
  window.webContents.on('did-finish-load', () => {
    setTimeout(() => {
      void window.webContents.capturePage().then((image) => {
        writeFileSync(target, image.toPNG())
        log('INFO', 'main', `screenshot saved to ${target}`)
      })
    }, 6000)
  })
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const [window] = BrowserWindow.getAllWindows()
    if (window) {
      if (window.isMinimized()) window.restore()
      window.focus()
    }
  })

  void app.whenReady().then(() => {
    ipcMain.handle(IPC.backendGet, () => backend.getInfo())
    backend.onChange((info) => {
      for (const window of BrowserWindow.getAllWindows()) {
        window.webContents.send(IPC.backendChanged, info)
      }
    })

    scheduleScreenshot(createWindow())
    void backend.start()
  })

  app.on('window-all-closed', () => app.quit())
  app.on('will-quit', () => backend.stop())
  process.on('exit', () => backend.stop())
}
