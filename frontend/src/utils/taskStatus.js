// One place for task status wording, so every page says the same thing for
// the same backend status. Unknown values fall back to a neutral label instead
// of leaking raw English to the page.

export const TASK_STATUS_LABELS = {
  pending: '等待开始',
  queued: '排队中',
  started: '已启动',
  starting: '启动中',
  running: '进行中',
  processing: '处理中',
  in_progress: '进行中',
  active: '进行中',
  paused: '已暂停',
  cancelling: '正在停止',
  stopping: '正在停止',
  completed: '已完成',
  done: '已完成',
  success: '成功',
  failed: '失败',
  error: '出错',
  cancelled: '已取消',
  canceled: '已取消',
  idle: '未开始',
  connected: '已连接',
  disconnected: '未连接',
  unknown: '状态未知',
}

const STATUS_TONES = {
  connected: 'success',
  completed: 'success',
  done: 'success',
  success: 'success',
  failed: 'danger',
  error: 'danger',
  disconnected: 'danger',
  pending: 'info',
  queued: 'info',
  started: 'info',
  starting: 'info',
  running: 'info',
  processing: 'info',
  in_progress: 'info',
  active: 'info',
  paused: 'warning',
  cancelling: 'warning',
  stopping: 'warning',
  cancelled: 'muted',
  canceled: 'muted',
  idle: 'muted',
  unknown: 'muted',
}

export const normalizeStatus = (status) => String(status ?? '').trim().toLowerCase()

export const taskStatusLabel = (status, fallback = '状态未知') => {
  const key = normalizeStatus(status)
  if (!key) return fallback
  return TASK_STATUS_LABELS[key] || fallback
}

export const taskStatusTone = (status) => STATUS_TONES[normalizeStatus(status)] || 'muted'

export const ACTIVE_TASK_STATUSES = new Set(['pending', 'queued', 'started', 'starting', 'running', 'processing', 'in_progress', 'paused', 'cancelling', 'stopping'])
export const TERMINAL_TASK_STATUSES = new Set(['completed', 'done', 'failed', 'error', 'cancelled', 'canceled'])
