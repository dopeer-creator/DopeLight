// Finds the uv executable. A terminal opened before uv was installed (or one
// whose parent app was) still has the old PATH, so also look in the places the
// uv installers put it.
import { spawnSync } from 'node:child_process'
import { homedir } from 'node:os'
import { join } from 'node:path'

const exe = process.platform === 'win32' ? 'uv.exe' : 'uv'

function candidates() {
  const list = ['uv', join(homedir(), '.local', 'bin', exe), join(homedir(), '.cargo', 'bin', exe)]
  if (process.env.LOCALAPPDATA) {
    list.push(
      join(
        process.env.LOCALAPPDATA,
        'Microsoft',
        'WinGet',
        'Packages',
        'astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe',
        exe
      )
    )
  }
  return list
}

/** Path (or bare name) of a working uv, or null when none is installed. */
export function findUv() {
  for (const candidate of candidates()) {
    const probe = spawnSync(candidate, ['--version'], { stdio: 'ignore' })
    if (!probe.error && probe.status === 0) return candidate
  }
  return null
}

export const UV_MISSING = 'Could not find uv. Install it with: winget install astral-sh.uv'
