import { dirname, join } from 'node:path'
import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import { IPC } from '@shared/types'
import { exportFolder } from './dev'

const FILTER_NAMES: Record<string, string> = { png: 'PNG image', jpg: 'JPEG image', tif: 'TIFF image' }

/** Folder of the last export in this run; the next save dialog starts there. */
let lastFolder: string | null = null

export function registerExportHandlers(): void {
  ipcMain.handle(IPC.exportChoosePath, async (event, defaultName: string, extension: string) => {
    const devFolder = exportFolder()
    if (devFolder) return join(devFolder, defaultName) // development: no dialog

    const window = BrowserWindow.fromWebContents(event.sender)
    const options = {
      title: 'Export',
      defaultPath: join(lastFolder ?? app.getPath('pictures'), defaultName),
      filters: [{ name: FILTER_NAMES[extension] ?? 'Image', extensions: [extension] }]
    }
    // The dialog itself asks before replacing an existing file.
    const result = window
      ? await dialog.showSaveDialog(window, options)
      : await dialog.showSaveDialog(options)
    if (result.canceled || !result.filePath) return null
    lastFolder = dirname(result.filePath)
    return result.filePath
  })

  ipcMain.on(IPC.exportReveal, (_event, path: string) => shell.showItemInFolder(path))
}
