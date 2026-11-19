import { safeHref } from '../../utils/safeUrl'

// Presentation-only helpers for the sign-in workspace. They decide how a task
// or a server message is *shown*; they never decide whether anything is sent.

// background: a server-side background job (opens its detail)
// history:    a recent recorded result
// guided:     a live activity the server only verified; the student finishes
//             it in 学习通 (e.g. the Rust preview marks these actionable:false)
// actionable: a live activity the manual form may submit
export const signinTaskKind = (task) => {
  const source = String(task?.source || '').toLowerCase()
  if (source === 'background') return 'background'
  if (source === 'history') return 'history'
  if (task?.actionable === false) {
    return source === 'live' || source === 'chat' ? 'guided' : 'background'
  }
  return 'actionable'
}

export const signinTaskId = (task) => String(task?.taskId || task?.task_id || '').trim()

const OFFICIAL_CONFIRM_PATH = '/newsign/preSign'
const isOfficialHost = (hostname) => hostname === 'chaoxing.com' || hostname.endsWith('.chaoxing.com')

// The only 学习通 page bound to a link is the official sign-in confirmation
// page (preSign), where the student finishes or checks the activity in the
// platform's own UI. The submit endpoint (submitSign) is a write URL and is
// never rendered as a link, whatever the server puts there.
export const signinPlatformUrl = (task) => {
  const href = safeHref(task?.remoteEndpoints?.endpoints?.preSign?.url)
  if (!href) return ''
  let url
  try {
    url = new URL(href)
  } catch (_) {
    return ''
  }
  if (url.protocol !== 'https:' || url.username || url.password || !isOfficialHost(url.hostname)) return ''
  if (url.pathname !== OFFICIAL_CONFIRM_PATH) return ''
  return url.href
}

const OPEN_STATUSES = new Set(['active', '', 'unknown'])

// A verified-but-not-submittable activity worth surfacing when no actionable
// one exists, so the page never claims "no sign-in" while one is open.
export const pickGuidedActiveTask = (tasks) => {
  if (!Array.isArray(tasks)) return null
  const candidates = tasks.filter(
    (task) => signinTaskKind(task) === 'guided' && OPEN_STATUSES.has(String(task?.status || '').toLowerCase())
  )
  if (candidates.length === 0) return null
  return [...candidates].sort((a, b) => {
    const aActive = String(a?.status || '').toLowerCase() === 'active' ? 0 : 1
    const bActive = String(b?.status || '').toLowerCase() === 'active' ? 0 : 1
    return aActive - bActive
  })[0]
}

// A sign-in may have been sent but its outcome was never confirmed.
const UNCONFIRMED_PATTERN = /未获确认|结果未确认|核对签到状态/
// The task's final result was never saved (no attempt marker either).
const UNSAVED_PATTERN = /最终结果未保存|结果未保存/
const PLATFORM_GUIDANCE_PATTERN = /(请?在学习通(App|\s*App|中)?(完成|核对|打开|处理))|(学习通\s*App\s*完成)|官方客户端/

// How a result message should read: a confirmed success, a failure, a
// "finish this in 学习通" hand-off, or an outcome that could not be confirmed.
export const classifyResult = (type, message) => {
  const text = String(message || '')
  if (UNCONFIRMED_PATTERN.test(text) || UNSAVED_PATTERN.test(text)) return 'unconfirmed'
  if (type !== 'success' && PLATFORM_GUIDANCE_PATTERN.test(text)) return 'guided'
  if (type === 'success') return 'done'
  if (type === 'error') return 'error'
  return 'info'
}

// Batch outcomes surface the item that most needs the student's attention:
// an unconfirmed result first, then a 学习通 hand-off, then a failure.
const RESULT_PRIORITY = ['unconfirmed', 'guided', 'error', 'info', 'done']

export const summarizeBatchResults = (results) => {
  const counts = { done: 0, unconfirmed: 0, guided: 0, error: 0, info: 0 }
  let lead = null
  for (const result of results) {
    const kind = classifyResult(result.status ? 'success' : 'error', result.message)
    counts[kind] += 1
    if (!lead || RESULT_PRIORITY.indexOf(kind) < RESULT_PRIORITY.indexOf(lead.kind)) {
      lead = { kind, name: result.name || '', message: String(result.message || '') }
    }
  }
  return { kind: lead?.kind || 'info', counts, lead }
}

export const TERMINAL_SIGNIN_STATUSES = new Set(['completed', 'error', 'failed', 'cancelled', 'canceled'])
const RUNNING_SIGNIN_STATUSES = new Set(['running', 'pending', 'processing', 'queued', 'started', 'starting', 'in_progress', 'in-progress'])
const STOPPING_SIGNIN_STATUSES = new Set(['cancelling', 'stopping'])

// One state for a background sign-in task, shared by the history list, the
// pending list and the detail pane. Unrecognised codes stay `unknown` and are
// never shown as running.
//   unconfirmed  a sign-in was attempted but its outcome is not confirmed
//   unsaved      the final result was never saved
//   running / stopping / done / guided / error / cancelled / unknown
export const classifyBackgroundTask = (task) => {
  if (!task || typeof task !== 'object') return 'unknown'
  const status = String(task.status || '').toLowerCase()
  const message = String(task.message || task.current_task || '')
  if (UNCONFIRMED_PATTERN.test(message)) return 'unconfirmed'
  if (UNSAVED_PATTERN.test(message)) return 'unsaved'
  if (RUNNING_SIGNIN_STATUSES.has(status)) return 'running'
  if (STOPPING_SIGNIN_STATUSES.has(status)) return 'stopping'
  if (status === 'completed') return PLATFORM_GUIDANCE_PATTERN.test(message) ? 'guided' : 'done'
  if (status === 'error' || status === 'failed') return 'error'
  if (status === 'cancelled' || status === 'canceled') return 'cancelled'
  return 'unknown'
}

export const isBackgroundTaskActive = (task) => {
  const state = classifyBackgroundTask(task)
  return state === 'running' || state === 'stopping'
}

const BACKGROUND_BADGE = {
  unconfirmed: { status: 'unconfirmed', label: '签到结果未确认' },
  unsaved: { status: 'unconfirmed', label: '最终结果未保存' },
  running: { status: 'running', label: '执行中' },
  stopping: { status: 'cancelling', label: '取消中' },
  done: { status: 'completed', label: '已完成' },
  guided: { status: 'guided', label: '需在学习通完成' },
  error: { status: 'error', label: '未全部完成' },
  cancelled: { status: 'cancelled', label: '已取消' },
  unknown: { status: 'unknown', label: '状态未知' },
}

export const backgroundTaskBadge = (task) => BACKGROUND_BADGE[classifyBackgroundTask(task)]

const toCount = (value) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0
}

// Progress for a background task: `current` is the processed count, while
// `completed` and `failed` are the successes and failures. Older records
// without `current` fall back to successes + failures.
export const backgroundTaskProgress = (progress) => {
  if (!progress || typeof progress !== 'object') return null
  const total = toCount(progress.total)
  const succeeded = toCount(progress.completed)
  const failed = toCount(progress.failed)
  const hasCurrent = progress.current !== undefined && progress.current !== null && progress.current !== ''
    && Number.isFinite(Number(progress.current))
  let processed = Math.max(hasCurrent ? toCount(progress.current) : 0, succeeded + failed)
  if (total > 0) processed = Math.min(processed, total)
  const currentCourse = typeof progress.current_course === 'string' ? progress.current_course : ''
  return { total, processed, succeeded, failed, currentCourse }
}

const SENSITIVE_KEY = /pass(word)?|pwd|cookie|token|secret|authorization|credential|session|photo_base64/i
const MAX_DEPTH = 6

// The raw-status disclosure is for diagnosis; it must never echo credentials
// or session material even if a server includes them by mistake.
export const redactForDisplay = (value, depth = 0) => {
  if (depth > MAX_DEPTH) return '…'
  if (Array.isArray(value)) return value.map((item) => redactForDisplay(item, depth + 1))
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        SENSITIVE_KEY.test(key) ? '••• 已隐藏' : redactForDisplay(item, depth + 1),
      ])
    )
  }
  return value
}
