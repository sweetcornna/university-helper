export {
  STATUS_LABEL as TASK_STATUS_LABELS,
  normalizeStatus,
  statusLabel as taskStatusLabel,
  statusTone as taskStatusTone,
} from '../components/statusMeta'

export const ACTIVE_TASK_STATUSES = new Set(['pending', 'queued', 'started', 'starting', 'running', 'processing', 'in_progress', 'paused', 'cancelling', 'stopping'])
export const TERMINAL_TASK_STATUSES = new Set(['completed', 'done', 'failed', 'error', 'cancelled', 'canceled'])
