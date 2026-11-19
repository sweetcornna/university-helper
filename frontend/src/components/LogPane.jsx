import { forwardRef } from 'react'
import { clsx } from 'clsx'

const LEVEL_TONES = {
  error: 'text-danger',
  warning: 'text-warning',
  warn: 'text-warning',
  success: 'text-success',
}

// Ledger-style log: one ruled line per entry, newest at the bottom. Entries
// are pre-formatted by the caller so each page keeps its own log contract.
const LogPane = forwardRef(function LogPane(
  { entries, label = '实时日志', emptyText = '暂无日志', className, live = true },
  ref,
) {
  return (
    <div
      ref={ref}
      role="log"
      aria-live={live ? 'polite' : 'off'}
      aria-label={label}
      className={clsx('log-pane ruled-paper', className)}
    >
      {entries.length === 0 ? (
        <p className="text-text-muted">{emptyText}</p>
      ) : (
        entries.map((entry) => (
          <p key={entry.key} className={clsx('break-all', LEVEL_TONES[entry.level] || '')}>
            {entry.time && <span className="mr-2 text-text-muted">{entry.time}</span>}
            {entry.text}
          </p>
        ))
      )}
    </div>
  )
})

export default LogPane
