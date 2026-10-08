import { Columns2, Download, Eye, FolderOpen, Redo2, Undo2 } from 'lucide-react'
import { useExportStore } from '../stores/exportStore'
import { useLightsStore } from '../stores/lightsStore'
import { useSessionStore } from '../stores/sessionStore'
import { useViewStore } from '../stores/viewStore'

export function Toolbar({ onOpen }: { onOpen: () => void }): React.JSX.Element {
  const canUndo = useLightsStore((store) => store.past.length > 0)
  const canRedo = useLightsStore((store) => store.future.length > 0)
  const ready = useSessionStore((store) => store.status === 'ready')
  const sourceName = useSessionStore((store) => store.sourceName)
  const comparing = useViewStore((store) => store.comparing)
  const split = useViewStore((store) => store.split)
  const { undo, redo } = useLightsStore.getState()
  const { setComparing, toggleSplit } = useViewStore.getState()

  return (
    <header className="toolbar">
      <div className="toolbar-group">
        <button className="button" title="Open image (Ctrl+O). You can also drop or paste one." onClick={onOpen}>
          <FolderOpen size={15} />
          Open
        </button>
        <button className="icon-button" title="Undo (Ctrl+Z)" disabled={!canUndo} onClick={undo}>
          <Undo2 size={16} />
        </button>
        <button className="icon-button" title="Redo (Ctrl+Y)" disabled={!canRedo} onClick={redo}>
          <Redo2 size={16} />
        </button>
      </div>

      <span className="toolbar-title">{sourceName ?? ''}</span>

      <div className="toolbar-group">
        <button
          className={`button ${comparing ? 'button--on' : ''}`}
          title="Hold to see the original (or hold C)"
          disabled={!ready}
          onPointerDown={() => setComparing(true)}
          onPointerUp={() => setComparing(false)}
          onPointerLeave={() => setComparing(false)}
        >
          <Eye size={15} />
          Compare
        </button>
        <button
          className={`button ${split ? 'button--on' : ''}`}
          title="Split view: original on the left, relit on the right"
          disabled={!ready}
          aria-pressed={split}
          onClick={toggleSplit}
        >
          <Columns2 size={15} />
          Split
        </button>
        <button
          className="button"
          title="Export the relit image or light layers (Ctrl+E)"
          disabled={!ready}
          onClick={useExportStore.getState().show}
        >
          <Download size={15} />
          Export
        </button>
      </div>
    </header>
  )
}
