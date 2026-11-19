// Shared presentation vocabulary for task details, history and badges.
export const STATUS_LABEL = {
  pending: '等待开始',
  queued: '排队中',
  started: '已启动',
  starting: '启动中',
  running: '进行中',
  processing: '处理中',
  in_progress: '进行中',
  'in-progress': '进行中',
  active: '进行中',
  paused: '已暂停',
  cancelling: '正在停止',
  stopping: '正在停止',
  unconfirmed: '结果未确认',
  guided: '需在学习通完成',
  completed: '已完成',
  done: '已完成',
  finished: '已完成',
  success: '成功',
  failed: '失败',
  error: '出错',
  cancelled: '已取消',
  canceled: '已取消',
  ended: '已结束',
  idle: '未开始',
  connected: '已连接',
  disconnected: '未连接',
  unknown: '状态未知',
}

const STATUS_TONE = {
  connected: 'success',
  completed: 'success',
  done: 'success',
  finished: 'success',
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
  'in-progress': 'info',
  active: 'info',
  paused: 'warning',
  cancelling: 'warning',
  stopping: 'warning',
  unconfirmed: 'warning',
  guided: 'warning',
}

export const normalizeStatus = (status) => String(status ?? '').trim().toLowerCase()
export const hasStatusLabel = (key) => Object.prototype.hasOwnProperty.call(STATUS_LABEL, key)

export const statusLabel = (status, fallback = '状态未知') => {
  const key = normalizeStatus(status)
  return hasStatusLabel(key) ? STATUS_LABEL[key] : fallback
}

export const statusTone = (status) => {
  const key = normalizeStatus(status)
  return Object.prototype.hasOwnProperty.call(STATUS_TONE, key) ? STATUS_TONE[key] : 'muted'
}
