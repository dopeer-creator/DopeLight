import type { RelightApi } from '@shared/types'

declare global {
  interface Window {
    relight: RelightApi
  }
}
