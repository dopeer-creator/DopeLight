/**
 * Light data model and the numbers the shading uses.
 *
 * SHADING must equal the constants in backend/relight_backend/pipeline/shading.py
 * (and DEPTH_SCALE in constants.py); backend/tests/test_shading.py checks that.
 */

export type LightType = 'point' | 'directional' | 'spot'

export interface Light {
  id: string
  name: string
  enabled: boolean
  type: LightType
  /** x, y: normalized image coords (y down), may go a little outside 0..1. z: height above the image plane, image-width units. */
  position: { x: number; y: number; z: number }
  /** Where directional and spot lights aim, normalized image coords. */
  target: { x: number; y: number }
  /** Linear RGB, each 0..1. */
  color: [number, number, number]
  intensity: number
  /** 0..1 softness: wider falloff, wrap lighting, softer shadow edge. */
  diffusion: number
  radius: number
  specular: number
  shininess: number
  /** Full cone angle in degrees (spot only). */
  coneAngle: number
  coneSoftness: number
  castShadows: boolean
  shadowStrength: number
}

export interface GlobalSettings {
  /** 0..2, flat fill light. */
  ambient: number
  /** In stops. */
  exposure: number
  /** 0..1, how much of the photo's own lighting stays. */
  keepOriginalLight: number
}

export const MAX_LIGHTS = 8
export const RECOMMENDED_LIGHTS = 3

export const SHADING = {
  depthScale: 0.4,
  wrapK: 1.0,
  specFade: 0.1,
  shadowBias: 0.006,
  shadowSoftMin: 0.012,
  shadowSoftMax: 0.08,
  shadowReach: 1.0,
  shadowThickness: 0.15,
  embedFade: 0.03,
  shellDilate: 0.004,
  rimStrength: 1.5,
  rimEdgeScale: 0.08,
  rimWidth: 0.0015,
  rimWhite: 0.35,
  softClipStart: 0.8,
  targetHeight: 0.5,
  defaultShadowSteps: 24
} as const

export const MAX_SHADOW_STEPS = 48

/** Slider ranges, shared by the panel and by input clamping. */
export const RANGES = {
  // The photo's relief spans z = 0 (farthest) to depthScale (nearest), so the low
  // end of this range puts a light behind foreground shapes.
  z: { min: 0.02, max: 2, step: 0.01 },
  intensity: { min: 0, max: 5, step: 0.01 },
  diffusion: { min: 0, max: 1, step: 0.01 },
  radius: { min: 0.05, max: 3, step: 0.01 },
  specular: { min: 0, max: 1, step: 0.01 },
  shininess: { min: 2, max: 200, step: 1 },
  coneAngle: { min: 5, max: 160, step: 1 },
  coneSoftness: { min: 0, max: 1, step: 0.01 },
  shadowStrength: { min: 0, max: 1, step: 0.01 },
  ambient: { min: 0, max: 2, step: 0.01 },
  exposure: { min: -3, max: 3, step: 0.01 },
  keepOriginalLight: { min: 0, max: 1, step: 0.01 },
  /** Lights may sit a little outside the picture. */
  position: { min: -0.25, max: 1.25, step: 0.005 }
} as const

export const DEFAULT_GLOBALS: GlobalSettings = { ambient: 0, exposure: 0, keepOriginalLight: 1 }

const DEFAULT_COLORS: [number, number, number][] = [
  [1, 0.86, 0.68], // warm key
  [0.55, 0.72, 1], // cool fill
  [1, 0.45, 0.6],
  [0.6, 1, 0.75]
]

/** A new light; `index` only varies its starting place and colour. */
export function createLight(id: string, index: number): Light {
  const spots = [
    { x: 0.3, y: 0.3 },
    { x: 0.72, y: 0.35 },
    { x: 0.5, y: 0.75 },
    { x: 0.2, y: 0.7 }
  ]
  const spot = spots[index % spots.length]!
  return {
    id,
    name: `Light ${index + 1}`,
    enabled: true,
    type: 'point',
    position: { x: spot.x, y: spot.y, z: 0.7 },
    target: { x: 0.5, y: 0.5 },
    color: DEFAULT_COLORS[index % DEFAULT_COLORS.length]!,
    intensity: 1.5,
    diffusion: 0.3,
    radius: 0.8,
    specular: 0.2,
    shininess: 32,
    coneAngle: 50,
    coneSoftness: 0.5,
    castShadows: false,
    shadowStrength: 0.7
  }
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

// --- colour ---------------------------------------------------------------

export function srgbToLinear(value: number): number {
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
}

export function linearToSrgb(value: number): number {
  const v = clamp(value, 0, 1)
  return v <= 0.0031308 ? v * 12.92 : 1.055 * v ** (1 / 2.4) - 0.055
}

/** "#rrggbb" (sRGB) to linear RGB. */
export function hexToLinear(hex: string): [number, number, number] {
  const n = Number.parseInt(hex.slice(1), 16)
  return [srgbToLinear(((n >> 16) & 255) / 255), srgbToLinear(((n >> 8) & 255) / 255), srgbToLinear((n & 255) / 255)]
}

/** Linear RGB to "#rrggbb" (sRGB). */
export function linearToHex(color: [number, number, number]): string {
  const channel = (v: number): string =>
    Math.round(linearToSrgb(v) * 255)
      .toString(16)
      .padStart(2, '0')
  return `#${channel(color[0])}${channel(color[1])}${channel(color[2])}`
}

// --- geometry (same formulas as shading.py) --------------------------------

/** Light position in shading space: x right, y up, z toward the viewer, image-width units. */
export function lightPosition(light: Light, aspect: number): [number, number, number] {
  return [light.position.x, (1 - light.position.y) * aspect, light.position.z]
}

/** Unit vector the light travels along: from its position toward its target. */
export function lightDirection(light: Light, aspect: number): [number, number, number] {
  const [px, py, pz] = lightPosition(light, aspect)
  const dx = light.target.x - px
  const dy = (1 - light.target.y) * aspect - py
  const dz = SHADING.depthScale * SHADING.targetHeight - pz
  const length = Math.hypot(dx, dy, dz) || 1
  return [dx / length, dy / length, dz / length]
}

/** [cos of the outer edge, cos of the inner edge] of a spot light's cone. */
export function coneCosines(light: Light): [number, number] {
  const half = (light.coneAngle * Math.PI) / 180 / 2
  const softness = clamp(light.coneSoftness, 0.01, 1)
  return [Math.cos(half), Math.cos(half * (1 - softness))]
}
