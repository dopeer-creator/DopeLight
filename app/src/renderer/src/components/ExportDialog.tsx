import { FolderOpen, X } from 'lucide-react'
import { DEFAULT_GLOBALS } from '@shared/lighting'
import {
  type BlendTarget,
  type ExportFormat,
  type ExportKind,
  useExportStore
} from '../stores/exportStore'
import { useLightsStore } from '../stores/lightsStore'

const KINDS: { value: ExportKind; label: string; hint: string }[] = [
  { value: 'relit', label: 'Relit image', hint: 'The finished picture, at the original size.' },
  {
    value: 'light_layer',
    label: 'Light layer',
    hint: 'Only what the lights add, on black. Put it over your photo in any editor with the Add (Linear Dodge) blend mode. A layer can only add light: it cannot darken.'
  },
  {
    value: 'per_light',
    label: 'One layer per light',
    hint: 'A separate light layer for each light, so you can balance them later. Together they add up to the light layer.'
  }
]

const FORMATS: { value: `${ExportFormat}-${8 | 16}`; label: string }[] = [
  { value: 'png-8', label: 'PNG, 8-bit' },
  { value: 'png-16', label: 'PNG, 16-bit' },
  { value: 'jpeg-8', label: 'JPEG' },
  { value: 'tiff-16', label: 'TIFF, 16-bit' }
]

const BLENDS: { value: BlendTarget; label: string; hint: string }[] = [
  {
    value: 'normal',
    label: 'Photoshop, Affinity, Krita',
    hint: 'For editors whose Add blend works on the stored values (the usual 8-bit and 16-bit documents).'
  },
  {
    value: 'linear',
    label: 'GIMP, 32-bit documents',
    hint: 'For Add in linear light: GIMP, 32-bit documents, or Photoshop with "Blend RGB colors using gamma 1.0".'
  }
]

export function ExportDialog(): React.JSX.Element | null {
  const { open, options, running, progress, message, files, error } = useExportStore()
  const { hide, setOptions, run, cancel } = useExportStore.getState()
  const globals = useLightsStore((store) => store.globals)
  if (!open) return null

  const layers = options.kind !== 'relit'
  const sceneChanged =
    globals.ambient !== DEFAULT_GLOBALS.ambient ||
    globals.exposure !== DEFAULT_GLOBALS.exposure ||
    globals.keepOriginalLight !== DEFAULT_GLOBALS.keepOriginalLight

  return (
    <div className="dialog-backdrop" onPointerDown={hide}>
      <div className="dialog" role="dialog" aria-label="Export" onPointerDown={(event) => event.stopPropagation()}>
        <header className="dialog-header">
          <h2>Export</h2>
          <button className="icon-button" title="Close (Esc)" disabled={running} onClick={hide}>
            <X size={16} />
          </button>
        </header>

        <div className="dialog-body">
          <div className="choice-list" role="radiogroup" aria-label="What to export">
            {KINDS.map((kind) => (
              <label key={kind.value} className="choice" title={kind.hint}>
                <input
                  type="radio"
                  name="export-kind"
                  checked={options.kind === kind.value}
                  disabled={running}
                  onChange={() => setOptions({ kind: kind.value })}
                />
                <span>
                  <strong>{kind.label}</strong>
                  <small>{kind.hint}</small>
                </span>
              </label>
            ))}
          </div>

          <label className="field">
            <span>Format</span>
            <select
              value={`${options.format}-${options.bitDepth}`}
              disabled={running}
              onChange={(event) => {
                const [format, depth] = event.target.value.split('-')
                setOptions({ format: format as ExportFormat, bitDepth: depth === '16' ? 16 : 8 })
              }}
            >
              {FORMATS.map((format) => (
                <option key={format.value} value={format.value}>
                  {format.label}
                </option>
              ))}
            </select>
          </label>

          {options.format === 'jpeg' && (
            <label className="field">
              <span>Quality</span>
              <input
                type="range"
                min={50}
                max={100}
                value={options.quality}
                disabled={running}
                onChange={(event) => setOptions({ quality: Number(event.target.value) })}
              />
              <span className="slider-value">{options.quality}</span>
            </label>
          )}

          {layers && (
            <>
              <label className="field" title={BLENDS.find((blend) => blend.value === options.blend)?.hint}>
                <span>Made for</span>
                <select
                  value={options.blend}
                  disabled={running}
                  onChange={(event) => setOptions({ blend: event.target.value as BlendTarget })}
                >
                  {BLENDS.map((blend) => (
                    <option key={blend.value} value={blend.value} title={blend.hint}>
                      {blend.label}
                    </option>
                  ))}
                </select>
              </label>
              <label
                className="check"
                title="Also saves each layer with transparency instead of black, for editors without an Add blend mode. Use it with the Normal blend mode."
              >
                <input
                  type="checkbox"
                  checked={options.alpha}
                  disabled={running}
                  onChange={(event) => setOptions({ alpha: event.target.checked })}
                />
                Also save a transparent version
              </label>
              {sceneChanged && (
                <p className="dialog-note">
                  Original light, Ambient, or Exposure is changed, so the layers belong on top of that
                  adjusted picture, not the untouched photo. It is saved too, as “_base”.
                </p>
              )}
            </>
          )}
        </div>

        <footer className="dialog-footer">
          {running ? (
            <>
              <div className="progress" role="progressbar" aria-valuenow={Math.round(progress * 100)}>
                <div className="progress-fill" style={{ width: `${progress * 100}%` }} />
              </div>
              <span className="dialog-status">{message}</span>
              <button className="button" onClick={cancel}>
                Cancel
              </button>
            </>
          ) : (
            <>
              {error !== null && <span className="dialog-status canvas-message--error">{error}</span>}
              {files.length > 0 && (
                <button className="button" title={files.join('\n')} onClick={() => window.relight.revealFile(files[0]!)}>
                  <FolderOpen size={15} />
                  Saved {files.length} file{files.length === 1 ? '' : 's'} · Show
                </button>
              )}
              {error === null && files.length === 0 && message && (
                <span className="dialog-status">{message}</span>
              )}
              <span className="status-spacer" />
              <button className="button button--primary" onClick={() => void run()}>
                Export…
              </button>
            </>
          )}
        </footer>
      </div>
    </div>
  )
}
