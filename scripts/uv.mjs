// Runs uv with the given arguments, wherever it is installed (see find-uv.mjs).
// Used by the root package.json scripts instead of calling `uv` directly.
import { spawnSync } from 'node:child_process'
import { findUv, UV_MISSING } from './find-uv.mjs'

const uv = findUv()
if (!uv) {
  console.error(UV_MISSING)
  process.exit(1)
}
const result = spawnSync(uv, process.argv.slice(2), { stdio: 'inherit' })
process.exit(result.status ?? 1)
