import { taskStatusLabel, taskStatusTone } from '../utils/taskStatus'

const TONES = {
  success: 'border-success/30 bg-success-surface text-success',
  danger: 'border-danger/30 bg-danger-surface text-danger',
  warning: 'border-warning/30 bg-warning-surface text-warning',
  info: 'border-primary/30 bg-primary/10 text-primary',
  muted: 'border-border bg-surface-hover text-text-muted',
}

// Labels and tones live in utils/taskStatus so every page names a status the
// same way (StatusBadge, task heroes, history lists).
export default function StatusBadge({ status, label, tone, className = '' }) {
  const toneKey = tone || taskStatusTone(status)
  const text = label || taskStatusLabel(status, String(status || '') || '状态未知')

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${TONES[toneKey] || TONES.muted} ${className}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {text}
    </span>
  )
}
