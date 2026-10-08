import { Dices, X } from 'lucide-react'
import { useBackendStore } from '../stores/backendStore'
import { useRenderStore } from '../stores/renderStore'

const ADHERENCE = { min: 0, max: 1, step: 0.01 }
const STEPS = { min: 8, max: 40, step: 1 }

/** Settings and progress for the photoreal pass. */
export function RenderDialog(): React.JSX.Element | null {
  const { open, options, running, progress, message, error } = useRenderStore()
  const { hide, setOptions, run, cancel } = useRenderStore.getState()
  const gpu = useBackendStore((store) => store.health?.gpu.available ?? false)
  if (!open) return null

  return (
    <div className="dialog-backdrop" onPointerDown={hide}>
      <div
        className="dialog"
        role="dialog"
        aria-label="Photoreal render"
        onPointerDown={(event) => event.stopPropagation()}
      >
        <header className="dialog-header">
          <h2>Photoreal render</h2>
          <button className="icon-button" title="Close (Esc)" disabled={running} onClick={hide}>
            <X size={16} />
          </button>
        </header>

        <div className="dialog-body">
          <p className="dialog-text">
            Redraws the photo's lighting with an AI model, following the lights you placed. The
            preview is the guide; this is the finished look. Your photo's detail is kept: only the
            light changes.
          </p>
          {!gpu && (
            <p className="dialog-note">
              No NVIDIA graphics card found, so this runs on the processor and can take many
              minutes. Turning off "Extra detail pass" and lowering Steps makes it faster.
            </p>
          )}

          <label className="field" title="Optional. Describes the mood of the light, for example: warm sunset light, cool moonlight, neon city lights.">
            <span>Describe light</span>
            <input
              type="text"
              value={options.prompt}
              disabled={running}
              onChange={(event) => setOptions({ prompt: event.target.value })}
            />
          </label>
          <label
            className="field"
            title="High: the light lands where you placed it, the look stays closer to the preview. Low: the model has more freedom and often looks more natural, but may move the light."
          >
            <span>Follow lights</span>
            <input
              type="range"
              {...ADHERENCE}
              value={options.adherence}
              disabled={running}
              onChange={(event) => setOptions({ adherence: Number(event.target.value) })}
            />
            <span className="slider-value">{options.adherence.toFixed(2)}</span>
          </label>
          <label className="field" title="More steps: cleaner result, proportionally slower.">
            <span>Steps</span>
            <input
              type="range"
              {...STEPS}
              value={options.steps}
              disabled={running}
              onChange={(event) => setOptions({ steps: Number(event.target.value) })}
            />
            <span className="slider-value">{options.steps}</span>
          </label>
          <label className="field" title="The same seed with the same settings gives the same result. Change it for a different take.">
            <span>Seed</span>
            <input
              type="number"
              value={options.seed}
              disabled={running}
              onChange={(event) => setOptions({ seed: Math.trunc(Number(event.target.value)) || 0 })}
            />
            <button
              className="icon-button"
              title="Random seed"
              disabled={running}
              onClick={() => setOptions({ seed: Math.floor(Math.random() * 1_000_000) })}
            >
              <Dices size={15} />
            </button>
          </label>
          <label className="check" title="A second pass at 1.5 times the size. Sharper light edges; about three times slower and needs more graphics memory.">
            <input
              type="checkbox"
              checked={options.highres}
              disabled={running}
              onChange={(event) => setOptions({ highres: event.target.checked })}
            />
            Extra detail pass
          </label>
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
              <span className={`dialog-status ${error !== null ? 'canvas-message--error' : ''}`} title={error ?? undefined}>
                {error ?? message}
              </span>
              <button className="button button--primary" onClick={() => void run()}>
                Render
              </button>
            </>
          )}
        </footer>
      </div>
    </div>
  )
}
