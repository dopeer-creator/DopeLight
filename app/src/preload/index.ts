import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron'
import { type BackendInfo, IPC, type RelightApi } from '@shared/types'

const api: RelightApi = {
  getBackend: () => ipcRenderer.invoke(IPC.backendGet) as Promise<BackendInfo>,
  onBackendChange: (callback) => {
    const listener = (_event: IpcRendererEvent, info: BackendInfo): void => callback(info)
    ipcRenderer.on(IPC.backendChanged, listener)
    return () => ipcRenderer.removeListener(IPC.backendChanged, listener)
  }
}

contextBridge.exposeInMainWorld('relight', api)
