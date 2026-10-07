import { appendFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { app } from 'electron'

type Level = 'INFO' | 'WARNING' | 'ERROR'

let logFile: string | null = null

function ensureLogFile(): string {
  if (logFile === null) {
    const dir = join(app.getPath('userData'), 'logs')
    mkdirSync(dir, { recursive: true })
    logFile = join(dir, 'main.log')
  }
  return logFile
}

/** One JSON object per line in %APPDATA%/<app>/logs/main.log, mirrored to the console. */
export function log(level: Level, source: string, message: string): void {
  const entry = { time: new Date().toISOString(), level, logger: source, message }
  console.log(`${level} ${source}: ${message}`)
  try {
    appendFileSync(ensureLogFile(), JSON.stringify(entry) + '\n')
  } catch {
    // Logging must never take the app down.
  }
}
