import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { runParity } from './parity'
import { useExportStore } from './stores/exportStore'
import { useLightsStore } from './stores/lightsStore'
import { useRenderStore } from './stores/renderStore'
import { useSessionStore } from './stores/sessionStore'
import { useViewStore } from './stores/viewStore'
import './styles.css'

// Development only: lets test scripts (scripts/ui-smoke.browser.js) read the app's state.
if (import.meta.env.DEV) {
  Object.assign(window, {
    __relight: {
      lights: useLightsStore,
      view: useViewStore,
      session: useSessionStore,
      exports: useExportStore,
      render: useRenderStore
    }
  })
}

if (window.location.hash === '#parity') {
  void runParity()
} else {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>
  )
}
