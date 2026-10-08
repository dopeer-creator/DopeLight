// UI smoke test: starts the real app, opens a sample photo, and runs
// scripts/ui-smoke.browser.js inside the page (drag, wheel, keys, buttons).
//   npm run ui-smoke
// Needs the sample photos (npm run samples) and the models (first open downloads them).
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const image = join(root, 'samples', 'portrait.jpg')
const out = join(tmpdir(), `relight-ui-smoke-${process.pid}.json`)
const exportDir = mkdtempSync(join(tmpdir(), 'relight-ui-smoke-export-'))
const TIMEOUT_MS = 15 * 60 * 1000 // first run may download models and preprocess on CPU

if (!existsSync(image)) {
  console.error('Missing samples/portrait.jpg. Run: npm run samples')
  process.exit(1)
}

const child = spawn('npm run dev', {
  cwd: join(root, 'app'),
  shell: true,
  stdio: 'ignore',
  env: {
    ...process.env,
    RELIGHT_OPEN: image,
    RELIGHT_SCRIPT: join(root, 'scripts', 'ui-smoke.browser.js'),
    RELIGHT_SCRIPT_OUT: out,
    RELIGHT_EXPORT_DIR: exportDir
  }
})

const started = Date.now()
const timer = setInterval(() => {
  if (existsSync(out)) finish(JSON.parse(readFileSync(out, 'utf8')))
  else if (Date.now() - started > TIMEOUT_MS) finish({ error: 'timed out waiting for the app' })
}, 500)

function finish(result) {
  clearInterval(timer)
  rmSync(out, { force: true })
  // The app quits itself after writing the result; make sure the dev server goes too.
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
  } else {
    child.kill('SIGTERM')
  }

  if (result.error) {
    rmSync(exportDir, { recursive: true, force: true })
    console.error(`UI smoke test could not run: ${result.error}`)
    process.exit(1)
  }
  // The export check is only real if the file is on disk.
  for (const file of result.files ?? []) {
    const size = existsSync(file) ? statSync(file).size : 0
    result.checks.push({
      name: 'exported file exists on disk',
      ok: size > 1000,
      detail: `${(size / 1e6).toFixed(1)} MB`
    })
  }
  rmSync(exportDir, { recursive: true, force: true })

  let failed = 0
  for (const { name, ok, detail } of result.checks) {
    if (!ok) failed++
    console.log(`${ok ? 'ok  ' : 'FAIL'}  ${name}${detail ? `  (${detail})` : ''}`)
  }
  console.log(`\n${result.checks.length - failed} of ${result.checks.length} checks passed`)
  process.exit(failed === 0 ? 0 : 1)
}
