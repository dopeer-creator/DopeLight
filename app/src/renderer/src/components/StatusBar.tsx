import { Cpu, Gauge } from 'lucide-react'
import type { BackendState, GpuStatus } from '@shared/types'
import { useBackendStore } from '../stores/backendStore'

const STATE_LABEL: Record<BackendState, string> = {
  starting: 'Starting backend…',
  running: 'Backend connected',
  stopped: 'Backend stopped',
  error: 'Backend error'
}

function formatGb(megabytes: number | null): string {
  return megabytes === null ? '?' : (megabytes / 1024).toFixed(1)
}

function gpuLabel(gpu: GpuStatus): string {
  return gpu.available ? (gpu.name ?? 'Unknown GPU') : 'No NVIDIA GPU found (CPU mode)'
}

export function StatusBar(): React.JSX.Element {
  const info = useBackendStore((store) => store.info)
  const health = useBackendStore((store) => store.health)
  const healthError = useBackendStore((store) => store.healthError)

  const detail = info.error ?? (info.state === 'running' ? healthError : null)

  return (
    <footer className="status-bar">
      <span className="status-item" title={detail ?? undefined}>
        <span className={`status-dot status-dot--${info.state}`} />
        {STATE_LABEL[info.state]}
        {detail !== null && <span className="status-detail">{detail}</span>}
      </span>

      {health !== null && (
        <>
          <span className="status-item">
            <Cpu size={13} />
            {gpuLabel(health.gpu)}
          </span>
          {health.gpu.available && (
            <span className="status-item">
              <Gauge size={13} />
              {formatGb(health.gpu.vram_free_mb)} / {formatGb(health.gpu.vram_total_mb)} GB VRAM free
            </span>
          )}
        </>
      )}

      <span className="status-spacer" />
      <span className="status-item status-item--muted">Idle</span>
    </footer>
  )
}
