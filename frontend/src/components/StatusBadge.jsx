const TONES = {
  success: 'border-success/30 bg-success-surface text-success',
  danger: 'border-danger/30 bg-danger-surface text-danger',
  warning: 'border-warning/30 bg-warning-surface text-warning',
  info: 'border-primary/30 bg-primary/10 text-primary',
  muted: 'border-border bg-surface-hover text-text-muted',
}

const STATUS_TONE = {
  connected: 'success',
  completed: 'success',
  success: 'success',
  active: 'success',
  done: 'success',
  error: 'danger',
  failed: 'danger',
  disconnected: 'danger',
  pending: 'info',
  running: 'info',
  starting: 'info',
  processing: 'info',
  queued: 'info',
  in_progress: 'info',
  paused: 'warning',
  cancelling: 'warning',
  cancelled: 'muted',
  idle: 'muted',
  unknown: 'muted',
}

const STATUS_LABEL = {
  connected: '已连接',
  completed: '已完成',
  success: '成功',
  active: '进行中',
  done: '已完成',
  error: '错误',
  failed: '失败',
  disconnected: '未连接',
  pending: '等待中',
  running: '进行中',
  starting: '启动中',
  processing: '处理中',
  queued: '排队中',
  in_progress: '进行中',
  paused: '已暂停',
  cancelling: '取消中',
  cancelled: '已取消',
  idle: '待开始',
  unknown: '未知',
}

export default function StatusBadge({ status, label, className = '' }) {
  const key = String(status || '').toLowerCase()
  const toneKey = STATUS_TONE[key] || 'muted'
  const text = label || STATUS_LABEL[key] || status || '未知'

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${TONES[toneKey]} ${className}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {text}
    </span>
  )
}
