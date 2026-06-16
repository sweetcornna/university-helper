/*
 * Consistent, token-driven status pill. Centralises the green/red/grey badge
 * styling (and English→中文 labels) that was previously re-implemented inline
 * on every list with raw Tailwind palette colours.
 */
const TONES = {
  success: 'border-success/30 bg-success-surface text-success',
  danger: 'border-danger/30 bg-danger-surface text-danger',
  warning: 'border-warning/30 bg-warning-surface text-warning',
  info: 'border-primary/30 bg-primary/10 text-primary',
  muted: 'border-border bg-surface-hover text-text-muted',
}

const STATUS_TONE = {
  completed: 'success',
  success: 'success',
  active: 'success',
  done: 'success',
  error: 'danger',
  failed: 'danger',
  pending: 'info',
  running: 'info',
  processing: 'info',
  queued: 'info',
  in_progress: 'info',
  paused: 'warning',
  cancelling: 'warning',
  cancelled: 'muted',
  unknown: 'muted',
}

const STATUS_LABEL = {
  completed: '已完成',
  success: '成功',
  active: '进行中',
  done: '已完成',
  error: '错误',
  failed: '失败',
  pending: '等待中',
  running: '进行中',
  processing: '处理中',
  queued: '排队中',
  in_progress: '进行中',
  paused: '已暂停',
  cancelling: '取消中',
  cancelled: '已取消',
  unknown: '未知',
}

export default function StatusBadge({ status, label, className = '' }) {
  const key = String(status || '').toLowerCase()
  const tone = TONES[STATUS_TONE[key]] || TONES.muted
  const text = label || STATUS_LABEL[key] || status || '未知'

  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${tone} ${className}`}
    >
      {text}
    </span>
  )
}
