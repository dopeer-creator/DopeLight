import { type ChildProcess, spawn, spawnSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { existsSync } from 'node:fs'
import { createServer } from 'node:net'
import { join } from 'node:path'
import { app } from 'electron'
import { BACKEND_HOST, TOKEN_ENV } from '@shared/constants'
import type { BackendInfo } from '@shared/types'
import { log } from './logger'

const HEALTH_POLL_MS = 250
const STARTUP_TIMEOUT_MS = 30_000
const STDERR_TAIL_LINES = 15

type Listener = (info: BackendInfo) => void

function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer()
    server.once('error', reject)
    server.listen(0, BACKEND_HOST, () => {
      const address = server.address()
      server.close(() => {
        if (address !== null && typeof address === 'object') resolve(address.port)
        else reject(new Error('Could not find a free port'))
      })
    })
  })
}

/** Backend source: next to app/ in dev, inside resources/ when packaged. */
function backendDir(): string {
  return app.isPackaged
    ? join(process.resourcesPath, 'backend')
    : join(app.getAppPath(), '..', 'backend')
}

/** Python from the uv-made venv: in the repo in dev, in %APPDATA% when packaged. */
function pythonPath(): string {
  const venv = app.isPackaged
    ? join(app.getPath('userData'), 'venv')
    : join(backendDir(), '.venv')
  return process.platform === 'win32'
    ? join(venv, 'Scripts', 'python.exe')
    : join(venv, 'bin', 'python')
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** Owns the Python child process: start, health wait, and guaranteed cleanup. */
export class BackendProcess {
  private child: ChildProcess | null = null
  private info: BackendInfo = { state: 'stopped', baseUrl: null, token: null, error: null }
  private readonly listeners = new Set<Listener>()
  private stderrTail: string[] = []

  getInfo(): BackendInfo {
    return this.info
  }

  onChange(listener: Listener): void {
    this.listeners.add(listener)
  }

  private update(patch: Partial<BackendInfo>): void {
    this.info = { ...this.info, ...patch }
    for (const listener of this.listeners) listener(this.info)
  }

  private fail(message: string): void {
    log('ERROR', 'backend', message)
    this.update({ state: 'error', error: message })
  }

  async start(): Promise<void> {
    if (this.child !== null) return

    const python = pythonPath()
    if (!existsSync(python)) {
      this.fail(`Python environment not found at ${python}. Run "uv sync" in the backend folder.`)
      return
    }

    const port = await findFreePort()
    const token = randomBytes(32).toString('hex')
    const baseUrl = `http://${BACKEND_HOST}:${port}`
    this.stderrTail = []
    this.update({ state: 'starting', baseUrl, token, error: null })

    // The backend watches our process id and exits when we are gone, even if
    // Electron is killed without running quit handlers.
    const child = spawn(
      python,
      ['-m', 'relight_backend.main', '--port', String(port), '--parent-pid', String(process.pid)],
      {
        cwd: backendDir(),
        env: { ...process.env, [TOKEN_ENV]: token, PYTHONUNBUFFERED: '1' },
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true
      }
    )
    this.child = child
    log('INFO', 'backend', `spawned pid ${child.pid} on port ${port}`)

    child.stdout?.on('data', (chunk: Buffer) => process.stdout.write(`[backend] ${chunk}`))
    child.stderr?.on('data', (chunk: Buffer) => {
      process.stderr.write(`[backend] ${chunk}`)
      const lines = chunk.toString().split(/\r?\n/).filter(Boolean)
      this.stderrTail = [...this.stderrTail, ...lines].slice(-STDERR_TAIL_LINES)
    })
    child.once('error', (error) => {
      if (this.child !== child) return
      this.child = null
      this.fail(`Could not start backend: ${error.message}`)
    })
    child.once('exit', (code) => {
      if (this.child !== child) return // we stopped it on purpose
      this.child = null
      this.fail(`Backend exited (code ${code}). ${this.stderrTail.join(' | ')}`.trim())
    })

    await this.waitUntilHealthy(child, baseUrl, token)
  }

  private async waitUntilHealthy(child: ChildProcess, baseUrl: string, token: string): Promise<void> {
    const deadline = Date.now() + STARTUP_TIMEOUT_MS
    while (this.child === child && Date.now() < deadline) {
      try {
        const response = await fetch(`${baseUrl}/health`, {
          headers: { Authorization: `Bearer ${token}` }
        })
        if (response.ok) {
          log('INFO', 'backend', 'healthy')
          this.update({ state: 'running' })
          return
        }
      } catch {
        // not listening yet
      }
      await sleep(HEALTH_POLL_MS)
    }
    if (this.child === child) {
      this.stop()
      this.fail(`Backend did not respond within ${STARTUP_TIMEOUT_MS / 1000} s.`)
    }
  }

  /** Synchronous so it is safe to call from quit handlers. */
  stop(): void {
    const child = this.child
    if (child === null) return
    this.child = null
    if (child.pid !== undefined) {
      if (process.platform === 'win32') {
        // The venv python.exe is a launcher with the real interpreter as its
        // child, so kill the whole tree.
        spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true })
      } else {
        child.kill('SIGTERM')
      }
    }
    log('INFO', 'backend', 'stopped')
    this.update({ state: 'stopped', baseUrl: null, token: null })
  }
}
