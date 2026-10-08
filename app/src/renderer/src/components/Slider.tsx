import { useLightsStore } from '../stores/lightsStore'

interface SliderProps {
  label: string
  value: number
  range: { min: number; max: number; step: number }
  onChange: (value: number) => void
  /** Digits after the decimal point in the readout. */
  digits?: number
  title?: string
}

const STEP_KEYS = new Set(['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'])

/** A labelled range input. One drag (or one key press) is one undo step. */
export function Slider({ label, value, range, onChange, digits = 2, title }: SliderProps): React.JSX.Element {
  const checkpoint = useLightsStore((store) => store.checkpoint)
  return (
    <label className="slider" title={title}>
      <span className="slider-label">{label}</span>
      <input
        type="range"
        min={range.min}
        max={range.max}
        step={range.step}
        value={value}
        onPointerDown={checkpoint}
        onKeyDown={(event) => {
          if (STEP_KEYS.has(event.key) && !event.repeat) checkpoint()
        }}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <span className="slider-value">{value.toFixed(digits)}</span>
    </label>
  )
}
