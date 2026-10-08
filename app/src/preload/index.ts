import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron'
import { type BackendInfo, IPC, type RelightApi } from '@shared/types'

const api: RelightApi = {
  getBackend: () => ipcRenderer.invoke(IPC.backendGet) as Promise<BackendInfo>,
  onBackendChange: (callback) => {
    const listener = (_event: IpcRendererEvent, info: BackendInfo): void => callback(info)
    ipcRenderer.on(IPC.backendChanged, listener)
    return () => ipcRenderer.removeListener(IPC.backendChanged, listener)
  },
  chooseExportPath: (defaultName, extension) =>
    ipcRenderer.invoke(IPC.exportChoosePath, defaultName, extension),
  revealFile: (path) => ipcRenderer.send(IPC.exportReveal, path),
  dev: {
    automation: () => ipcRenderer.invoke(IPC.devAutomation),
    ready: () => ipcRenderer.send(IPC.devReady),
    parityLoad: () => ipcRenderer.invoke(IPC.parityLoad),
    parityResult: (name, pixels) => ipcRenderer.invoke(IPC.parityResult, name, pixels),
    parityFinish: (error) => ipcRenderer.invoke(IPC.parityFinish, error)
  }
}

contextBridge.exposeInMainWorld('relight', api)
