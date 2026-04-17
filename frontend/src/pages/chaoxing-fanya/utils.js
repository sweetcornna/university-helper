export const TOKEN_ERROR = /(invalid token|token has expired|token validation failed|missing token|invalid authentication credentials)/i


export const POLL_MS = 2500


export const DONE_STATUSES = new Set(['completed', 'failed', 'error', 'cancelled'])


export const RESTORE_STATUSES = new Set(['running', 'pending', 'paused'])


export const CARD = 'rounded-2xl border border-white/20 bg-white/80 p-6 shadow-lg backdrop-blur-lg'


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
