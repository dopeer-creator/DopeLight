import { ChevronDown, ChevronUp, Copy, Eye, EyeOff, Plus, Trash2 } from 'lucide-react'
import {
  hexToLinear,
  type Light,
  type LightType,
  linearToHex,
  MAX_LIGHTS,
  RANGES,
  RECOMMENDED_LIGHTS
} from '@shared/lighting'
import { useLightsStore } from '../stores/lightsStore'
import { surfaceHeightAt } from '../gl/renderer'
import { useSessionStore } from '../stores/sessionStore'
import { Slider } from './Slider'

/** The Close · Far slider runs the other way from z (z grows toward the viewer). */
const FAR_FLIP = RANGES.z.min + RANGES.z.max

const TYPES: { value: LightType; label: string; hint: string }[] = [
  { value: 'point', label: 'Point', hint: 'Shines in all directions from one spot' },
  { value: 'spot', label: 'Spot', hint: 'A cone of light aimed at a target' },
  { value: 'directional', label: 'Sun', hint: 'Parallel light from far away, aimed at a target' }
]

function LightRow({ light, index, count }: { light: Light; index: number; count: number }): React.JSX.Element {
  const selected = useLightsStore((store) => store.selectedId === light.id)
  const { select, updateLight, checkpoint, duplicateLight, deleteLight, moveLight } =
    useLightsStore.getState()
  return (
    <li
      className={`light-row ${selected ? 'light-row--selected' : ''} ${light.enabled ? '' : 'light-row--off'}`}
      onClick={() => select(light.id)}
    >
      <span className="light-swatch" style={{ background: linearToHex(light.color) }} />
      <span className="light-name">{light.name}</span>
      <span className="light-actions" onClick={(event) => event.stopPropagation()}>
        <button
          className="icon-button"
          title={light.enabled ? 'Turn off' : 'Turn on'}
          onClick={() => {
            checkpoint()
            updateLight(light.id, { enabled: !light.enabled })
          }}
        >
          {light.enabled ? <Eye size={14} /> : <EyeOff size={14} />}
        </button>
        <button className="icon-button" title="Move up" disabled={index === 0} onClick={() => moveLight(light.id, -1)}>
          <ChevronUp size={14} />
        </button>
        <button
          className="icon-button"
          title="Move down"
          disabled={index === count - 1}
          onClick={() => moveLight(light.id, 1)}
        >
          <ChevronDown size={14} />
        </button>
        <button
          className="icon-button"
          title="Duplicate"
          disabled={count >= MAX_LIGHTS}
          onClick={() => duplicateLight(light.id)}
        >
          <Copy size={14} />
        </button>
        <button className="icon-button" title="Delete (Del)" onClick={() => deleteLight(light.id)}>
          <Trash2 size={14} />
        </button>
      </span>
    </li>
  )
}

function LightProperties({ light }: { light: Light }): React.JSX.Element {
  const { updateLight, checkpoint } = useLightsStore.getState()
  const set = (patch: Partial<Light>): void => updateLight(light.id, patch)
  const local = light.type !== 'directional' // has a place in space, so distance matters
  const maps = useSessionStore((store) => store.maps)
  const surface = maps && local ? surfaceHeightAt(maps, light.position.x, light.position.y) : null

  return (
    <div className="panel-section">
      <div className="segmented" role="radiogroup" aria-label="Light type">
        {TYPES.map((type) => (
          <button
            key={type.value}
            role="radio"
            aria-checked={light.type === type.value}
            className={light.type === type.value ? 'segmented--on' : ''}
            title={type.hint}
            onClick={() => {
              checkpoint()
              set({ type: type.value })
            }}
          >
            {type.label}
          </button>
        ))}
      </div>

      <label className="slider">
        <span className="slider-label">Color</span>
        <input
          type="color"
          value={linearToHex(light.color)}
          onPointerDown={checkpoint}
          onChange={(event) => set({ color: hexToLinear(event.target.value) })}
        />
      </label>
      <Slider label="Intensity" value={light.intensity} range={RANGES.intensity} onChange={(intensity) => set({ intensity })} />
      <Slider
        label="Diffusion"
        title="Softness: wider falloff, light wraps around shapes, softer shadow edges"
        value={light.diffusion}
        range={RANGES.diffusion}
        onChange={(diffusion) => set({ diffusion })}
      />
      {local && (
        <Slider
          label="Radius"
          title="How far the light reaches before fading"
          value={light.radius}
          range={RANGES.radius}
          onChange={(radius) => set({ radius })}
        />
      )}
      {/* Position, as three sliders like Photoshop's Relight panel. Dragging the dot
          in the picture moves the first two; the mouse wheel moves the third. */}
      <Slider
        label="Left · Right"
        value={light.position.x}
        range={RANGES.position}
        onChange={(x) => set({ position: { ...light.position, x } })}
      />
      <Slider
        label="Low · High"
        value={1 - light.position.y}
        range={RANGES.position}
        onChange={(high) => set({ position: { ...light.position, y: 1 - high } })}
      />
      <Slider
        label="Close · Far"
        title="Toward you or away from you. Far enough, and the light is behind things in the photo. Also: mouse wheel over the picture"
        value={FAR_FLIP - light.position.z}
        range={RANGES.z}
        onChange={(far) => set({ position: { ...light.position, z: FAR_FLIP - far } })}
      />
      {surface !== null && (
        <p className={`depth-note ${light.position.z < surface ? 'depth-note--behind' : ''}`}>
          {light.position.z < surface
            ? `Behind the surface under it (surface at ${surface.toFixed(2)}). Lights the background and rims edges.`
            : `In front of the surface under it (surface at ${surface.toFixed(2)}).`}
        </p>
      )}
      {light.type === 'spot' && (
        <>
          <Slider label="Cone" digits={0} value={light.coneAngle} range={RANGES.coneAngle} onChange={(coneAngle) => set({ coneAngle })} />
          <Slider label="Cone edge" value={light.coneSoftness} range={RANGES.coneSoftness} onChange={(coneSoftness) => set({ coneSoftness })} />
        </>
      )}
      <Slider label="Specular" title="Strength of shiny highlights" value={light.specular} range={RANGES.specular} onChange={(specular) => set({ specular })} />
      <Slider label="Shininess" digits={0} title="Higher = smaller, tighter highlights" value={light.shininess} range={RANGES.shininess} onChange={(shininess) => set({ shininess })} />

      <label className="check">
        <input
          type="checkbox"
          checked={light.castShadows}
          onChange={(event) => {
            checkpoint()
            set({ castShadows: event.target.checked })
          }}
        />
        Cast shadows
      </label>
      {light.castShadows && (
        <Slider label="Shadow" value={light.shadowStrength} range={RANGES.shadowStrength} onChange={(shadowStrength) => set({ shadowStrength })} />
      )}
    </div>
  )
}

export function LightsPanel(): React.JSX.Element {
  const lights = useLightsStore((store) => store.lights)
  const selected = useLightsStore((store) => store.lights.find((light) => light.id === store.selectedId))
  const globals = useLightsStore((store) => store.globals)
  const { addLight, updateGlobals } = useLightsStore.getState()

  return (
    <aside className="panel">
      <header className="panel-header">
        <h2>Lights</h2>
        <button
          className="icon-button"
          title={lights.length >= MAX_LIGHTS ? `At most ${MAX_LIGHTS} lights` : 'Add light (L)'}
          disabled={lights.length >= MAX_LIGHTS}
          onClick={addLight}
        >
          <Plus size={16} />
        </button>
      </header>

      {lights.length === 0 ? (
        <p className="panel-hint">No lights yet. Press L or the + button to add one.</p>
      ) : (
        <ul className="light-list">
          {lights.map((light, index) => (
            <LightRow key={light.id} light={light} index={index} count={lights.length} />
          ))}
        </ul>
      )}
      {lights.length > RECOMMENDED_LIGHTS && (
        <p className="panel-hint">
          {RECOMMENDED_LIGHTS} or fewer lights usually look best and keep the preview fastest.
        </p>
      )}

      {selected && <LightProperties light={selected} />}

      <header className="panel-header">
        <h2>Scene</h2>
      </header>
      <div className="panel-section">
        <Slider
          label="Original light"
          title="How much of the photo's own lighting stays"
          value={globals.keepOriginalLight}
          range={RANGES.keepOriginalLight}
          onChange={(keepOriginalLight) => updateGlobals({ keepOriginalLight })}
        />
        <Slider label="Ambient" title="Flat fill light everywhere" value={globals.ambient} range={RANGES.ambient} onChange={(ambient) => updateGlobals({ ambient })} />
        <Slider label="Exposure" title="Overall brightness, in stops" value={globals.exposure} range={RANGES.exposure} onChange={(exposure) => updateGlobals({ exposure })} />
        <Slider
          label="Even light"
          title="Evens out the photo's own lighting under your lights: bright areas take less new light, dark areas more. Stops bright photos from blowing out."
          value={globals.flatten}
          range={RANGES.flatten}
          onChange={(flatten) => updateGlobals({ flatten })}
        />
        <Slider
          label="Smooth surface"
          title="Smooths the estimated surface. Hides blocky patches, noise, and false bumps; too much loses real detail."
          value={globals.smoothing}
          range={RANGES.smoothing}
          onChange={(smoothing) => updateGlobals({ smoothing })}
        />
      </div>
    </aside>
  )
}
