import { useEffect } from 'react'
import { APP_NAME } from '@shared/constants'
import { StatusBar } from './components/StatusBar'
import { useBackendStore } from './stores/backendStore'

const HEALTH_POLL_MS = 2000

export function App(): React.JSX.Element {
  const state = useBackendStore((store) => store.info.state)
  const setInfo = useBackendStore((store) => store.setInfo)
  const refreshHealth = useBackendStore((store) => store.refreshHealth)

  useEffect(() => {
    void window.relight.getBackend().then(setInfo)
    return window.relight.onBackendChange(setInfo)
  }, [setInfo])

  useEffect(() => {
    if (state !== 'running') return
    void refreshHealth()
    const timer = setInterval(() => void refreshHealth(), HEALTH_POLL_MS)
    return () => clearInterval(timer)
  }, [state, refreshHealth])

  return (
    <div className="app">
      <main className="canvas-area">
        <div className="empty-state">
          <h1>{APP_NAME}</h1>
          <p>Image loading arrives in Phase 2.</p>
        </div>
      </main>
      <StatusBar />
    </div>
  )
}
