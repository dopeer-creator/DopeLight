import { useCallback, useEffect, useRef, useState } from 'react'
import { ImagePlus } from 'lucide-react'
import { APP_NAME } from '@shared/constants'
import type { GlobalSettings, Light } from '@shared/lighting'
import { CanvasView } from './components/CanvasView'
import { ExportDialog } from './components/ExportDialog'
import { LightsPanel } from './components/LightsPanel'
import { RenderDialog } from './components/RenderDialog'
import { StatusBar } from './components/StatusBar'
import { Toolbar } from './components/Toolbar'
import { benchmarkShader } from './gl/benchmark'
import { useShortcuts } from './hooks/useShortcuts'
import { useBackendStore } from './stores/backendStore'
import { useLightsStore } from './stores/lightsStore'
import { useSessionStore } from './stores/sessionStore'
import { useViewStore } from './stores/viewStore'

const HEALTH_POLL_MS = 2000

function firstImage(files: FileList | null | undefined): File | null {
  return Array.from(files ?? []).find((file) => file.type.startsWith('image/')) ?? null
}

/** What fills the canvas area when there is no picture to show. */
function StageMessage({ onOpen }: { onOpen: () => void }): React.JSX.Element | null {
  const status = useSessionStore((store) => store.status)
  const progress = useSessionStore((store) => store.progress)
  const message = useSessionStore((store) => store.message)
  const error = useSessionStore((store) => store.error)
  const backendUp = useBackendStore((store) => store.info.state === 'running')
  const cancel = useSessionStore((store) => store.cancel)

  if (status === 'ready') return null
  if (status === 'working') {
    return (
      <div className="canvas-message">
        <p>{message || 'Working'}</p>
        <div className="progress" role="progressbar" aria-valuenow={Math.round(progress * 100)}>
          <div className="progress-fill" style={{ width: `${progress * 100}%` }} />
        </div>
        <button className="button" onClick={cancel}>
          Cancel
        </button>
      </div>
    )
  }
  return (
    <div className="canvas-message">
      <h1>{APP_NAME}</h1>
      {status === 'error' && <p className="canvas-message--error">Could not open the image: {error}</p>}
      <button className="button button--primary" disabled={!backendUp} onClick={onOpen}>
        <ImagePlus size={16} />
        Open an image
      </button>
      <p>or drop one here, or paste from the clipboard</p>
    </div>
  )
}

export function App(): React.JSX.Element {
  const backendState = useBackendStore((store) => store.info.state)
  const setInfo = useBackendStore((store) => store.setInfo)
  const refreshHealth = useBackendStore((store) => store.refreshHealth)
  const ready = useSessionStore((store) => store.status === 'ready')
  const fileInput = useRef<HTMLInputElement>(null)
  const [dropping, setDropping] = useState(false)

  const openDialog = useCallback(() => fileInput.current?.click(), [])
  const openFile = useCallback((file: File | null) => {
    if (file) void useSessionStore.getState().open({ name: file.name || 'pasted image.png', data: file })
  }, [])
  useShortcuts(openDialog)

  useEffect(() => {
    void window.relight.getBackend().then(setInfo)
    return window.relight.onBackendChange(setInfo)
  }, [setInfo])

  useEffect(() => {
    if (backendState !== 'running') return
    void refreshHealth()
    const timer = setInterval(() => void refreshHealth(), HEALTH_POLL_MS)
    return () => clearInterval(timer)
  }, [backendState, refreshHealth])

  // Paste an image from the clipboard.
  useEffect(() => {
    const paste = (event: ClipboardEvent): void => openFile(firstImage(event.clipboardData?.files))
    window.addEventListener('paste', paste)
    return () => window.removeEventListener('paste', paste)
  }, [openFile])

  // Development helper: open an image (and a saved scene) named by environment variables.
  useEffect(() => {
    if (backendState !== 'running') return
    void window.relight.dev.automation().then(async (automation) => {
      if (!automation.openImage) return
      const { name, bytes } = automation.openImage
      await useSessionStore.getState().open({ name, data: new Blob([bytes as BlobPart]) })
      if (automation.scene) {
        const scene = JSON.parse(automation.scene) as {
          lights: Light[]
          globals?: GlobalSettings
          split?: number
        }
        useLightsStore.getState().reset(scene.lights, scene.globals)
        if (scene.split !== undefined) useViewStore.setState({ split: true, splitAt: scene.split })
      }
      if (useSessionStore.getState().status !== 'ready') return
      if (automation.bench) benchmarkShader()
      window.relight.dev.ready()
    })
  }, [backendState])

  return (
    <div
      className={`app ${dropping ? 'app--dropping' : ''}`}
      onDragOver={(event) => {
        event.preventDefault()
        setDropping(true)
      }}
      onDragLeave={() => setDropping(false)}
      onDrop={(event) => {
        event.preventDefault()
        setDropping(false)
        openFile(firstImage(event.dataTransfer.files))
      }}
    >
      <input
        ref={fileInput}
        type="file"
        accept="image/*"
        hidden
        onChange={(event) => {
          openFile(firstImage(event.target.files))
          event.target.value = '' // so picking the same file again still fires
        }}
      />
      <Toolbar onOpen={openDialog} />
      <div className="workspace">
        <main className="stage-area">
          <CanvasView />
          <StageMessage onOpen={openDialog} />
        </main>
        {ready && <LightsPanel />}
      </div>
      <StatusBar />
      <ExportDialog />
      <RenderDialog />
    </div>
  )
}
