import { join } from 'node:path'
import { app, BrowserWindow, ipcMain, shell } from 'electron'
import { APP_NAME } from '@shared/constants'
import { IPC } from '@shared/types'
import { BackendProcess } from './backend'
import { attachDevHelpers, parityFolder, registerDevHandlers } from './dev'
import { registerExportHandlers } from './exportDialog'
import { log } from './logger'

app.setName(APP_NAME)

const backend = new BackendProcess()
/** Parity runs render a fixture with the shader and quit; no backend, no visible window. */
const parityRun = parityFolder() !== undefined

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

  if (!parityRun) window.once('ready-to-show', () => window.show())

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

  // A page that loads twice or a renderer that dies should be visible in the log.
  window.webContents.on('did-finish-load', () => log('INFO', 'main', 'page loaded'))
  window.webContents.on('render-process-gone', (_event, details) => {
    log('ERROR', 'main', `renderer process gone: ${details.reason} (exit code ${details.exitCode})`)
  })

  const hash = parityRun ? 'parity' : ''
  const devUrl = process.env['ELECTRON_RENDERER_URL']
  if (!app.isPackaged && devUrl) void window.loadURL(`${devUrl}#${hash}`)
  else void window.loadFile(join(__dirname, '../renderer/index.html'), { hash })

  return window
}

if (!parityRun && !app.requestSingleInstanceLock()) {
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
    registerExportHandlers()
    registerDevHandlers()

    attachDevHelpers(createWindow())
    if (!parityRun) void backend.start()
  })

  app.on('window-all-closed', () => app.quit())
  app.on('will-quit', () => backend.stop())
  process.on('exit', () => backend.stop())
}
