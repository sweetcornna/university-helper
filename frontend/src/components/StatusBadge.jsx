import { AlertTriangle, CheckCircle2, CircleDashed, CircleSlash, HelpCircle, Loader2, PauseCircle, XCircle } from 'lucide-react'
import { hasStatusLabel, normalizeStatus, statusLabel, statusTone } from './statusMeta'

const TONES = {
  success: 'border-success/35 bg-success-surface text-success',
  danger: 'border-danger/35 bg-danger-surface text-danger',
  warning: 'border-warning/35 bg-warning-surface text-warning',
  info: 'border-primary/35 bg-primary/10 text-primary',
  muted: 'border-border bg-surface-hover text-text-muted',
}

const TONE_ICONS = {
  success: CheckCircle2,
  danger: XCircle,
  warning: AlertTriangle,
  info: Loader2,
  muted: CircleDashed,
}

export default function StatusBadge({ status, label, tone, className = '' }) {
  const key = normalizeStatus(status)
  const unknown = key && !hasStatusLabel(key)
  const toneKey = tone || statusTone(key)
  const Icon = key === 'paused'
    ? PauseCircle
    : key === 'cancelled' || key === 'canceled'
      ? CircleSlash
      : unknown && !tone && !label
        ? HelpCircle
        : TONE_ICONS[toneKey] || CircleDashed

  return (
    <span
      title={unknown ? `状态代码：${status}` : undefined}
      className={`inline-flex shrink-0 items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold leading-5 ${TONES[toneKey] || TONES.muted} ${className}`}
    >
      <Icon className={`h-3.5 w-3.5 ${Icon === Loader2 ? 'motion-safe:animate-spin' : ''}`} aria-hidden="true" />
      {label || statusLabel(key)}
    </span>
  )
}
