import {
  coneCosines,
  type GlobalSettings,
  type Light,
  lightDirection,
  lightPosition,
  MAX_LIGHTS,
  MAX_SHADOW_STEPS,
  SHADING
} from '@shared/lighting'
import { FRAGMENT_SHADER, VERTEX_SHADER } from './shader'

/** Why raw WebGL2 and not Three.js: this is one triangle and one shader; a scene graph adds 600 kB and nothing else. */

export interface RelightMaps {
  /** sRGB image at working size. */
  albedo: TexImageSource
  /** Normal map image, rgb = n * 0.5 + 0.5. */
  normal: TexImageSource
  /** The same normals, blurred. */
  normalSmooth: TexImageSource
  /** Helper maps: red = where lights reach, green = sqrt of large-scale brightness. */
  aux: TexImageSource
  /** Depth 0..1 (1 = nearest), row by row from the top. */
  depth: Float32Array
  width: number
  height: number
}

export type ViewMode = 'relit' | 'original' | 'lightOnly'

/** Height of the photo's surface at a point (normalized image coords), in the light's z units. */
export function surfaceHeightAt(maps: RelightMaps, x: number, y: number): number {
  const column = Math.min(maps.width - 1, Math.max(0, Math.floor(x * maps.width)))
  const row = Math.min(maps.height - 1, Math.max(0, Math.floor(y * maps.height)))
  return SHADING.depthScale * maps.depth[row * maps.width + column]!
}

/** Radius, in pixels, of the "top nearby" filter for a map of this width. Same as shading.py. */
export function dilateRadius(width: number): number {
  return Math.max(1, Math.floor(width * SHADING.shellDilate + 0.5))
}

/** Highest (or lowest) value within a square window of 2 * radius + 1: rows, then columns. */
function windowExtreme(
  values: Float32Array, width: number, height: number, radius: number, pick: (a: number, b: number) => number
): Float32Array {
  const rows = new Float32Array(values.length)
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const to = Math.min(width - 1, x + radius)
      let best = values[y * width + Math.max(0, x - radius)]!
      for (let i = Math.max(0, x - radius) + 1; i <= to; i++) best = pick(best, values[y * width + i]!)
      rows[y * width + x] = best
    }
  }
  const result = new Float32Array(values.length)
  for (let y = 0; y < height; y++) {
    const from = Math.max(0, y - radius)
    const to = Math.min(height - 1, y + radius)
    for (let x = 0; x < width; x++) {
      let best = rows[from * width + x]!
      for (let i = from + 1; i <= to; i++) best = pick(best, rows[i * width + x]!)
      result[y * width + x] = best
    }
  }
  return result
}

/** Highest depth within `radius` pixels. */
export function dilateDepth(depth: Float32Array, width: number, height: number, radius: number): Float32Array {
  return windowExtreme(depth, width, height, radius, Math.max)
}

/** Reach of the outline map, in multiples of the rim radius. Same as RIM_REACH in shading.py. */
const RIM_REACH = [1, 2, 3, 4]

/** Pixel unit of the outline's width for a map of this width. Same as rim_radius() in shading.py. */
export function rimRadius(width: number): number {
  return Math.max(1, Math.floor(width * SHADING.rimWidth + 0.5))
}

/**
 * Outline strength, 0..1: how much a pixel stands above the lowest depth near
 * it, averaged over four distances. It is 1 right on the near side of a depth
 * edge and fades over a few pixels inward. Same as outline_map() in shading.py.
 */
export function outlineMap(depth: Float32Array, width: number, height: number): Float32Array {
  const radius = rimRadius(width)
  const outline = new Float32Array(depth.length)
  let lowest = depth
  let reached = 0
  for (const reach of RIM_REACH) {
    // Lowest-value windows compose: widening by the difference gives the larger window.
    lowest = windowExtreme(lowest, width, height, (reach - reached) * radius, Math.min)
    reached = reach
    for (let i = 0; i < depth.length; i++) {
      const step = (depth[i]! - lowest[i]!) / SHADING.rimEdgeScale
      outline[i]! += Math.min(1, Math.max(0, step)) / RIM_REACH.length
    }
  }
  return outline
}

/**
 * How far a light is below the photo's surface at its own spot (> 0 = behind it).
 * A directional light has no spot: +-1000 by whether it shines from behind.
 * Same rule as light_embed() in shading.py.
 */
export function lightEmbed(light: Light, maps: RelightMaps): number {
  if (light.type === 'directional') {
    return lightDirection(light, maps.height / maps.width)[2] > 0 ? 1000 : -1000
  }
  return surfaceHeightAt(maps, light.position.x, light.position.y) - light.position.z
}

export interface DrawParams {
  lights: Light[]
  globals: GlobalSettings
  mode: ViewMode
  /** 0..1: pixels left of this x show the original. null = off. */
  split: number | null
  shadowSteps?: number
  /** 0 = no jitter, 1 = one full step. */
  jitter?: number
}

const TYPE_INDEX = { point: 0, directional: 1, spot: 2 } as const
const MODE_INDEX: Record<ViewMode, number> = { relit: 0, original: 1, lightOnly: 2 }

const UNIFORMS = [
  'uAlbedo', 'uNormal', 'uDepth', 'uNormalSmooth', 'uAux', 'uSmoothing', 'uFlatten', 'uAspect', 'uLightCount', 'uType', 'uPosition', 'uDirection',
  'uColor', 'uDiffusion', 'uRadius', 'uSpecular', 'uShininess', 'uCone', 'uShadow', 'uEmbed', 'uBase',
  'uGain', 'uShadowSteps', 'uJitter', 'uMode', 'uSplit'
] as const
type UniformName = (typeof UNIFORMS)[number]

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type)!
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(`Shader compile failed: ${gl.getShaderInfoLog(shader)}`)
  }
  return shader
}

export class RelightRenderer {
  private readonly gl: WebGL2RenderingContext
  private readonly program: WebGLProgram
  private readonly vao: WebGLVertexArrayObject
  private readonly locations = {} as Record<UniformName, WebGLUniformLocation | null>
  private readonly floatLinear: boolean
  private textures: WebGLTexture[] = []
  private maps: RelightMaps | null = null
  private readonly syncPixel = new Uint8Array(4)
  private aspect = 1
  private ready = false

  constructor(private readonly canvas: HTMLCanvasElement | OffscreenCanvas) {
    const gl = canvas.getContext('webgl2', {
      alpha: false,
      antialias: false,
      depth: false,
      stencil: false,
      powerPreference: 'high-performance'
    }) as WebGL2RenderingContext | null
    if (!gl) throw new Error('WebGL2 is not available on this graphics driver.')
    this.gl = gl
    this.floatLinear = gl.getExtension('OES_texture_float_linear') !== null

    const program = gl.createProgram()!
    gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER))
    gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER))
    gl.linkProgram(program)
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error(`Shader link failed: ${gl.getProgramInfoLog(program)}`)
    }
    this.program = program
    for (const name of UNIFORMS) this.locations[name] = gl.getUniformLocation(program, name)
    this.vao = gl.createVertexArray()! // the triangle is built from gl_VertexID; no buffers
  }

  /** Upload the three maps. Call once per image; after that only uniforms change. */
  setMaps(maps: RelightMaps): void {
    const gl = this.gl
    for (const texture of this.textures) gl.deleteTexture(texture)
    this.aspect = maps.height / maps.width
    this.maps = maps

    // Upload bytes exactly as decoded: no flip, no alpha premultiply, no colour management.
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false)
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false)
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE)
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1)

    // sRGB internal format: the GPU converts to linear light when sampling.
    const albedo = this.createTexture(0, true)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.SRGB8_ALPHA8, gl.RGBA, gl.UNSIGNED_BYTE, maps.albedo)
    gl.generateMipmap(gl.TEXTURE_2D)

    const normal = this.createTexture(1, true)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, maps.normal)
    gl.generateMipmap(gl.TEXTURE_2D)

    // 32-bit float keeps the full 16-bit depth precision; half float is the
    // fallback when the driver cannot filter 32-bit float textures.
    // Three channels: the depth; the highest depth within a few pixels (for
    // shadows of lights behind the surface); and the outline strength (rim light).
    const tops = dilateDepth(maps.depth, maps.width, maps.height, dilateRadius(maps.width))
    const outline = outlineMap(maps.depth, maps.width, maps.height)
    const packed = new Float32Array(maps.depth.length * 3)
    for (let i = 0; i < maps.depth.length; i++) {
      packed[i * 3] = maps.depth[i]!
      packed[i * 3 + 1] = tops[i]!
      packed[i * 3 + 2] = outline[i]!
    }
    const depth = this.createTexture(2, false)
    const format = this.floatLinear ? gl.RGB32F : gl.RGB16F
    gl.texImage2D(gl.TEXTURE_2D, 0, format, maps.width, maps.height, 0, gl.RGB, gl.FLOAT, packed)

    const normalSmooth = this.createTexture(3, true)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, maps.normalSmooth)
    gl.generateMipmap(gl.TEXTURE_2D)

    const aux = this.createTexture(4, false)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, maps.aux)

    this.textures = [albedo, normal, depth, normalSmooth, aux]
    this.ready = true
  }

  private createTexture(unit: number, mipmaps: boolean): WebGLTexture {
    const gl = this.gl
    const texture = gl.createTexture()!
    gl.activeTexture(gl.TEXTURE0 + unit)
    gl.bindTexture(gl.TEXTURE_2D, texture)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mipmaps ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    return texture
  }

  /** Draw one frame at the canvas's current pixel size. */
  draw(params: DrawParams): void {
    if (!this.ready) return
    const gl = this.gl
    const u = this.locations
    const lights = params.lights.filter((light) => light.enabled).slice(0, MAX_LIGHTS)

    const types = new Int32Array(MAX_LIGHTS)
    const positions = new Float32Array(MAX_LIGHTS * 3)
    const directions = new Float32Array(MAX_LIGHTS * 3)
    const colors = new Float32Array(MAX_LIGHTS * 3)
    const cones = new Float32Array(MAX_LIGHTS * 2)
    const diffusion = new Float32Array(MAX_LIGHTS)
    const radius = new Float32Array(MAX_LIGHTS).fill(1)
    const specular = new Float32Array(MAX_LIGHTS)
    const shininess = new Float32Array(MAX_LIGHTS).fill(1)
    const shadow = new Float32Array(MAX_LIGHTS)
    const embed = new Float32Array(MAX_LIGHTS)
    const maps = this.maps!

    lights.forEach((light, i) => {
      types[i] = TYPE_INDEX[light.type]
      positions.set(lightPosition(light, this.aspect), i * 3)
      directions.set(lightDirection(light, this.aspect), i * 3)
      colors.set(light.color.map((channel) => channel * light.intensity), i * 3)
      cones.set(coneCosines(light), i * 2)
      diffusion[i] = light.diffusion
      radius[i] = light.radius
      specular[i] = light.specular
      shininess[i] = light.shininess
      shadow[i] = light.castShadows ? light.shadowStrength : 0
      embed[i] = lightEmbed(light, maps)
    })

    gl.viewport(0, 0, this.canvas.width, this.canvas.height)
    gl.useProgram(this.program)
    gl.bindVertexArray(this.vao)
    this.textures.forEach((texture, unit) => {
      gl.activeTexture(gl.TEXTURE0 + unit)
      gl.bindTexture(gl.TEXTURE_2D, texture)
    })

    gl.uniform1i(u.uAlbedo, 0)
    gl.uniform1i(u.uNormal, 1)
    gl.uniform1i(u.uDepth, 2)
    gl.uniform1i(u.uNormalSmooth, 3)
    gl.uniform1i(u.uAux, 4)
    gl.uniform1f(u.uSmoothing, params.globals.smoothing)
    gl.uniform1f(u.uFlatten, params.globals.flatten)
    gl.uniform1f(u.uAspect, this.aspect)
    gl.uniform1i(u.uLightCount, lights.length)
    gl.uniform1iv(u.uType, types)
    gl.uniform3fv(u.uPosition, positions)
    gl.uniform3fv(u.uDirection, directions)
    gl.uniform3fv(u.uColor, colors)
    gl.uniform2fv(u.uCone, cones)
    gl.uniform1fv(u.uDiffusion, diffusion)
    gl.uniform1fv(u.uRadius, radius)
    gl.uniform1fv(u.uSpecular, specular)
    gl.uniform1fv(u.uShininess, shininess)
    gl.uniform1fv(u.uShadow, shadow)
    gl.uniform1fv(u.uEmbed, embed)
    gl.uniform1f(u.uBase, params.globals.keepOriginalLight + params.globals.ambient)
    gl.uniform1f(u.uGain, 2 ** params.globals.exposure)
    const steps = Math.min(params.shadowSteps ?? SHADING.defaultShadowSteps, MAX_SHADOW_STEPS)
    gl.uniform1i(u.uShadowSteps, steps)
    gl.uniform1f(u.uJitter, params.jitter ?? 1)
    gl.uniform1i(u.uMode, MODE_INDEX[params.mode])
    gl.uniform1f(u.uSplit, params.split ?? -1)

    gl.drawArrays(gl.TRIANGLES, 0, 3)
  }

  /** The frame just drawn, as RGBA bytes from the top row down. Call right after draw(). */
  readPixels(): Uint8Array {
    const gl = this.gl
    const { width, height } = this.canvas
    const bottomUp = new Uint8Array(width * height * 4)
    gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, bottomUp)
    const topDown = new Uint8Array(bottomUp.length)
    const row = width * 4
    for (let y = 0; y < height; y++) {
      topDown.set(bottomUp.subarray((height - 1 - y) * row, (height - y) * row), y * row)
    }
    return topDown
  }

  /**
   * Block until the GPU has finished the frame; used to time rendering.
   * Reading a pixel back is the one call that truly waits (gl.finish() returns
   * early in Chromium).
   */
  finish(): void {
    this.gl.readPixels(0, 0, 1, 1, this.gl.RGBA, this.gl.UNSIGNED_BYTE, this.syncPixel)
  }

  dispose(): void {
    const gl = this.gl
    for (const texture of this.textures) gl.deleteTexture(texture)
    gl.deleteProgram(this.program)
    gl.deleteVertexArray(this.vao)
    this.ready = false
  }
}
