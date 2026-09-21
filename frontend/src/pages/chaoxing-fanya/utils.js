export const TOKEN_ERROR = /(invalid token|token has expired|token validation failed|missing token|invalid authentication credentials)/i


export const POLL_MS = 2500


export const DONE_STATUSES = new Set(['completed', 'failed', 'error', 'cancelled'])


export const RESTORE_STATUSES = new Set(['running', 'pending', 'paused'])


export const CARD = 'rounded-2xl border border-border/20 bg-surface/80 p-6 shadow-lg backdrop-blur-lg'


export const toNum = (value, fallback = 0) => {


  const n = Number(value)


  return Number.isFinite(n) ? n : fallback


}


export const toTimestamp = (value) => {


  const ts = new Date(value).getTime()


  return Number.isFinite(ts) ? ts : 0


}


export const normalizeCourseText = (value) => {


  if (value === undefined || value === null) return ''


  return String(value).trim()


}


export const getCourseId = (course) => {


  const courseId = normalizeCourseText(course?.courseId ?? course?.course_id)


  const classId = normalizeCourseText(course?.classId ?? course?.clazzId ?? course?.class_id ?? course?.clazz_id)


  const cpi = normalizeCourseText(course?.cpi)


  if (courseId && classId) {


    return cpi ? `${courseId}_${classId}_${cpi}` : `${courseId}_${classId}`


  }


  const explicitId = normalizeCourseText(course?.id)


  return explicitId || courseId || classId


}


export const getCourseName = (course) => {
  const name = [
    course?.name,
    course?.courseName,
    course?.title,
    course?.course_name,
    course?.courseTitle,
    course?.course_title,
    course?.className,
    course?.clazzName,
    course?.label,
  ]
    .map(normalizeCourseText)
    .find(Boolean)
  const selector = getCourseId(course)
  return name || (selector ? `课程 ${selector}` : '未命名课程')
}


export const normalizeTaskItem = (task) => {


  if (!task || typeof task !== 'object') return null


  const taskId = String(task.task_id || task.taskId || task.id || '').trim()


  if (!taskId) return null


  const status = String(task.status || task.task_status || task.state || 'unknown').toLowerCase()


  const updatedAt =


    task.updated_at ||


    task.updatedAt ||


    task.update_time ||


    task.last_update ||


    task.started_at ||


    task.start_time ||


    task.created_at ||


    new Date().toISOString()


  return { ...task, task_id: taskId, status, updated_at: updatedAt }


}


export const mergeTaskHistory = (prev, incoming, prepend = false) => {


  const incomingList = (Array.isArray(incoming) ? incoming : [incoming]).map(normalizeTaskItem).filter(Boolean)


  if (incomingList.length === 0) return prev


  const incomingMap = new Map(incomingList.map((item) => [item.task_id, item]))


  const seen = new Set()


  const merged = []


  const push = (item) => {


    if (!item?.task_id || seen.has(item.task_id)) return


    seen.add(item.task_id)


    merged.push(item)


  }


  if (prepend) {


    incomingList.forEach(push)


    prev.forEach((item) => push(incomingMap.get(item.task_id) || item))


    return merged


  }


  prev.forEach((item) => push(incomingMap.get(item.task_id) || item))


  incomingList.forEach(push)


  return merged


}


export const formatTaskTime = (value) => {


  if (!value) return '--'


  const date = new Date(value)


  if (Number.isNaN(date.getTime())) return String(value)


  return date.toLocaleString('zh-CN', { hour12: false })


}

const CN_DIGITS = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']

// 1 -> 一, 11 -> 十一, 21 -> 二十一. Past 99 the numeral stops being readable,
// so fall back to the plain number rather than emitting 三百二十一.
export const toChineseNumeral = (value) => {
  const n = Math.trunc(Number(value))
  if (!Number.isFinite(n) || n < 1) return String(value ?? '')
  if (n < 10) return CN_DIGITS[n]
  if (n === 10) return '十'
  if (n < 20) return `十${CN_DIGITS[n - 10]}`
  if (n < 100) {
    const tens = Math.floor(n / 10)
    const ones = n % 10
    return `${CN_DIGITS[tens]}十${ones ? CN_DIGITS[ones] : ''}`
  }
  return String(n)
}

// Chinese labels for a task's raw status. The raw value stays available
// (rendered as a tooltip) so the English token is still recoverable for
// debugging, but the list itself reads in the same language as the rest of the
// page.
const TASK_STATUS_TEXT = {
  started: '运行中',
  running: '运行中',
  pending: '等待中',
  paused: '已暂停',
  cancelling: '取消中',
  cancelled: '已取消',
  completed: '已完成',
  failed: '失败',
  error: '失败',
}

export const taskStatusLabel = (status) => {
  const raw = String(status || '').toLowerCase()
  return TASK_STATUS_TEXT[raw] || raw || '未知'
}

// Newest first, each row carrying a sequential 任务一 / 任务二 / … label.
//
// The label exists because `task_id` is an opaque 32-char hex string: it says
// nothing to a reader and a column of them is unreadable. Numbering follows the
// displayed order so the labels run top-to-bottom in step with the list.
export const labelTaskHistory = (taskHistory) =>
  [...(taskHistory || [])]
    .sort((a, b) => toTimestamp(b?.updated_at) - toTimestamp(a?.updated_at))
    .map((task, index) => ({ ...task, label: `任务${toChineseNumeral(index + 1)}` }))
