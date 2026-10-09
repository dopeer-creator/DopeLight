import { useEffect, useState } from 'react'

function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/**
 * What a running job is doing: the message in full, the time since it started,
 * and a bar underneath. Mounted when the job starts, so the clock starts then.
 */
export function JobProgress({ progress, message }: { progress: number; message: string }): React.JSX.Element {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const started = Date.now()
    const timer = window.setInterval(() => setSeconds(Math.round((Date.now() - started) / 1000)), 1000)
    return () => window.clearInterval(timer)
  }, [])

  return (
    <div className="job-progress">
      <div className="job-progress-text">
        <span>{message}</span>
        <span className="job-progress-time" title="Time since this started">
          {clock(seconds)}
        </span>
      </div>
      <div className="progress progress--wide" role="progressbar" aria-valuenow={Math.round(progress * 100)}>
        <div className="progress-fill" style={{ width: `${progress * 100}%` }} />
      </div>
    </div>
  )
}
