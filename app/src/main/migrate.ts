import { existsSync, renameSync } from 'node:fs'
import { join } from 'node:path'
import { app } from 'electron'
import { DATA_DIR_ENV, LEGACY_APP_NAMES } from '@shared/constants'

/**
 * The app was called "Relight" at first. Its data folder holds gigabytes of
 * downloaded models, so on the first start under the new name the old folder
 * is renamed instead of everything being downloaded again.
 *
 * Must run before anything creates the new folder (logging, the backend).
 */
export function migrateDataFolder(): void {
  // With the data folder set elsewhere, the default one is not in use: leave it alone.
  if (process.env[DATA_DIR_ENV]) return
  const current = app.getPath('userData')
  if (existsSync(current)) return
  for (const name of LEGACY_APP_NAMES) {
    const legacy = join(app.getPath('appData'), name)
    if (!existsSync(legacy)) continue
    try {
      renameSync(legacy, current)
    } catch {
      // In use or not permitted: start fresh; the old folder is left untouched.
    }
    return
  }
}
