// Creates/updates backend/.venv with the PyTorch build that fits this machine:
// CUDA 12.6 wheels when an NVIDIA GPU is present, CPU wheels otherwise.
// Override with RELIGHT_TORCH=cpu or RELIGHT_TORCH=cu126.
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { findUv, UV_MISSING } from './find-uv.mjs'

const BUILDS = ['cpu', 'cu126']
const backendDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'backend')

function detectBuild() {
  const probe = spawnSync('nvidia-smi', ['--query-gpu=name', '--format=csv,noheader'], {
    encoding: 'utf8'
  })
  const gpu = probe.status === 0 ? probe.stdout.trim().split('\n')[0] : ''
  console.log(gpu ? `NVIDIA GPU found: ${gpu}` : 'No NVIDIA GPU found (nvidia-smi missing or failed)')
  return gpu ? 'cu126' : 'cpu'
}

const build = process.env.RELIGHT_TORCH ?? detectBuild()
if (!BUILDS.includes(build)) {
  console.error(`RELIGHT_TORCH must be one of: ${BUILDS.join(', ')}`)
  process.exit(1)
}

console.log(`Installing backend packages with PyTorch build "${build}"...`)
const uv = findUv()
if (!uv) {
  console.error(UV_MISSING)
  process.exit(1)
}
const result = spawnSync(uv, ['sync', '--directory', backendDir, '--extra', build], {
  stdio: 'inherit'
})
process.exit(result.status ?? 1)
