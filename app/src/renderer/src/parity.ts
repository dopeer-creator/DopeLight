import type { GlobalSettings, Light } from '@shared/lighting'
import { RelightRenderer, type ViewMode } from './gl/renderer'

/**
 * Parity run (development only): draw the fixture's scenes with the real
 * shader and hand the pixels to the main process, which writes them to disk
 * for scripts/parity.py to compare with the Python reference.
 */

interface ParityScene {
  name: string
  lights: Light[]
  globals: GlobalSettings
  mode: ViewMode
  split: number | null
  shadowSteps: number
  jitter: number
}

interface ParityFile {
  width: number
  height: number
  scenes: ParityScene[]
}

const RAW_BITMAP: ImageBitmapOptions = { colorSpaceConversion: 'none', premultiplyAlpha: 'none' }

function pngBitmap(bytes: Uint8Array): Promise<ImageBitmap> {
  return createImageBitmap(new Blob([bytes as BlobPart], { type: 'image/png' }), RAW_BITMAP)
}

/** Raw little-endian uint16 depth to floats in 0..1. */
export function depthFromUint16(bytes: Uint8Array): Float32Array {
  const values = new Uint16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 2)
  const depth = new Float32Array(values.length)
  for (let i = 0; i < values.length; i++) depth[i] = values[i]! / 65535
  return depth
}

export async function runParity(): Promise<void> {
  try {
    const fixture = await window.relight.dev.parityLoad()
    if (!fixture) throw new Error('No parity fixture (RELIGHT_PARITY is not set)')
    const file = JSON.parse(fixture.scenes) as ParityFile

    const canvas = new OffscreenCanvas(file.width, file.height)
    const renderer = new RelightRenderer(canvas)
    renderer.setMaps({
      albedo: await pngBitmap(fixture.albedo),
      normal: await pngBitmap(fixture.normal),
      normalSmooth: await pngBitmap(fixture.normalSmooth),
      aux: await pngBitmap(fixture.aux),
      // Copy: the IPC buffer may not be aligned for a Uint16Array view.
      depth: depthFromUint16(fixture.depth.slice()),
      width: file.width,
      height: file.height
    })

    for (const scene of file.scenes) {
      renderer.draw(scene)
      await window.relight.dev.parityResult(scene.name, renderer.readPixels())
    }
    await window.relight.dev.parityFinish(null)
  } catch (error) {
    await window.relight.dev.parityFinish(error instanceof Error ? error.message : String(error))
  }
}
