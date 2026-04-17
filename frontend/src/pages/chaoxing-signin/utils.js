import jsQR from 'jsqr'

// ── Constants ──────────────────────────────────────────────────────────────────

export const POLL_INTERVAL_MS = 3000

export const CHAOXING_API_BASE = '/api/v1/chaoxing'

export const CHAOXING_SETTINGS_KEY = 'chaoxing_signin_settings_v1'

export const DEFAULT_CHECK_INTERVAL_MINUTES = 5

export const MIN_CHECK_INTERVAL_MINUTES = 1

export const MAX_CHECK_INTERVAL_MINUTES = 60

export const AUTO_SIGN_TASK_COOLDOWN_MS = 2 * 60 * 1000

export const BACKGROUND_TASK_MAX_ITEMS = 50

export const BACKGROUND_RUNNING_STATUS_SET = new Set(['running', 'pending', 'processing', 'queued', 'in_progress', 'in-progress'])

export const TOKEN_ERROR_PATTERN = /(invalid token|token has expired|token validation failed|missing token)/i

export const GLASS_CARD_CLASS = 'rounded-2xl border border-white/20 bg-white/80 p-6 shadow-lg backdrop-blur-lg transition-all duration-200'

export const GLASS_PANEL_CLASS = 'rounded-xl border border-white/30 bg-white/60 p-4 backdrop-blur-sm transition-all duration-200'

export const SIGN_TYPE_FALLBACK_MAP = {

}

// ── Pure utility functions ─────────────────────────────────────────────────────

export const parsePayload = async (response) => {

  const text = await response.text()

  if (!text) return {}

  try {

    return JSON.parse(text)

  } catch (_) {

    return { message: text }

  }

}



export const pickMessage = (payload) => {

  if (!payload) return ''

  return payload.msg || payload.message || payload.detail || payload.data?.message || ''

}



export const appendPayloadToFormData = (formData, payload) => {

  Object.entries(payload).forEach(([key, value]) => {

    if (value === null || value === undefined || value === '') return

    if (Array.isArray(value) || (typeof value === 'object' && !(value instanceof File))) {

      formData.append(key, JSON.stringify(value))

      return

    }

    formData.append(key, String(value))

  })

}



export const clampCheckInterval = (value) => {

  const parsed = Number(value)

  if (!Number.isFinite(parsed)) return DEFAULT_CHECK_INTERVAL_MINUTES

  return Math.min(MAX_CHECK_INTERVAL_MINUTES, Math.max(MIN_CHECK_INTERVAL_MINUTES, Math.floor(parsed)))

}



export const safeStringify = (value) => {

  try {

    return JSON.stringify(value)

  } catch (_) {

    return '[Unserializable log]'

  }

}



export const normalizeCourseText = (value) => String(value ?? '').trim()



export const buildCourseSelector = (course) => {

  const existingId = normalizeCourseText(course?.id)

  if (existingId.includes('_')) return existingId



  const courseId = normalizeCourseText(course?.courseId || course?.course_id || course?.rawCourseId || existingId)

  const classId = normalizeCourseText(course?.classId || course?.clazzId || course?.class_id || course?.clazz_id)

  const cpi = normalizeCourseText(course?.cpi)



  if (courseId && classId) {

    return cpi ? `${courseId}_${classId}_${cpi}` : `${courseId}_${classId}`

  }



  return courseId || classId

}



export const getCourseDisplayName = (course, fallbackLabel = '') => {
  const name = [
    course?.courseName,
    course?.name,
    course?.title,
    course?.course_name,
    course?.courseTitle,
    course?.course_title,
    course?.className,
    course?.clazzName,
  ]
    .map(normalizeCourseText)
    .find(Boolean)
  const selector = buildCourseSelector(course)
  return name || fallbackLabel || (selector ? `课程 ${selector}` : '未命名课程')
}

export const normalizeSignTypeForApi = (value) => {

  return SIGN_TYPE_FALLBACK_MAP[value] || value || 'all'

}



export const shouldUseLocationParams = (value) => {

  return value === 'location' || value === 'qrcode' || value === 'gesture' || value === 'all'

}



export const fileToBase64 = (file) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result
      const base64 = result.includes(',') ? result.split(',')[1] : result
      resolve(base64)
    }
    reader.onerror = () => reject(new Error('文件读取失败'))
    reader.readAsDataURL(file)
  })
}

export const decodeQrCodeFromFile = (file) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const img = new Image()
      img.onload = () => {
        const canvas = document.createElement('canvas')
        canvas.width = img.width
        canvas.height = img.height
        const ctx = canvas.getContext('2d')
        ctx.drawImage(img, 0, 0)
        const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
        const code = jsQR(imageData.data, imageData.width, imageData.height)
        if (code && code.data) {
          resolve(code.data)
        } else {
          reject(new Error('无法识别二维码，请确认图片包含有效的二维码。'))
        }
      }
      img.onerror = () => reject(new Error('图片加载失败，请重新选择。'))
      img.src = reader.result
    }
    reader.onerror = () => reject(new Error('文件读取失败，请重新选择。'))
    reader.readAsDataURL(file)
  })
}

export const parseTaskTimestamp = (value) => {

  if (value === undefined || value === null || value === '') return 0

  if (typeof value === 'number') {

    return value > 1e12 ? value : value * 1000

  }

  const parsed = new Date(value).getTime()

  return Number.isFinite(parsed) ? parsed : 0

}



export const extractBackgroundTaskId = (task) => {

  const rawId = task?.task_id ?? task?.taskId ?? task?.id

  if (rawId === undefined || rawId === null || rawId === '') return ''

  return String(rawId).trim()

}



export const normalizeBackgroundTaskRecord = (task = {}) => {

  const normalizedTaskId = extractBackgroundTaskId(task)

  if (!normalizedTaskId) return null

  const updatedAt = task?.updated_at || task?.updatedAt || task?.timestamp || task?.created_at || task?.createdAt || ''

  const createdAt = task?.created_at || task?.createdAt || updatedAt || ''

  return {

    taskId: normalizedTaskId,

    status: String(task?.status || task?.state || task?.task_status || task?.taskStatus || 'unknown').toLowerCase(),

    message: String(task?.message || task?.detail || task?.msg || ''),

    courseName: String(task?.courseName || task?.course_name || task?.name || task?.title || ''),

    signType: String(task?.sign_type || task?.type || ''),

    progress: task?.progress && typeof task.progress === 'object' ? task.progress : null,

    updatedAt,

    createdAt

  }

}



export const sortBackgroundTasks = (tasks) => {

  return [...tasks].sort((a, b) => {

    const aTime = parseTaskTimestamp(a.updatedAt || a.createdAt)

    const bTime = parseTaskTimestamp(b.updatedAt || b.createdAt)

    return bTime - aTime

  })

}



export const normalizeBackgroundTaskHistory = (payload) => {

  const candidates = [

    payload?.data?.tasks,

    payload?.data?.list,

    payload?.data?.history,

    payload?.data?.records,

    payload?.data,

    payload?.tasks,

    payload?.list,

    payload?.history,

    payload?.records,

    payload

  ]

  const source = candidates.find((candidate) => Array.isArray(candidate)) || []

  const taskMap = new Map()



  source.forEach((task) => {

    const normalized = normalizeBackgroundTaskRecord(task)

    if (!normalized) return

    const existing = taskMap.get(normalized.taskId)

    if (!existing) {

      taskMap.set(normalized.taskId, normalized)

      return

    }

    const existingTime = parseTaskTimestamp(existing.updatedAt || existing.createdAt)

    const nextTime = parseTaskTimestamp(normalized.updatedAt || normalized.createdAt)

    taskMap.set(normalized.taskId, nextTime >= existingTime ? { ...existing, ...normalized } : existing)

  })



  return sortBackgroundTasks(Array.from(taskMap.values())).slice(0, BACKGROUND_TASK_MAX_ITEMS)

}



export const upsertBackgroundTaskHistory = (history, task) => {

  const normalized = normalizeBackgroundTaskRecord(task)

  if (!normalized) return history

  const merged = [normalized, ...(history || []).filter((item) => item.taskId !== normalized.taskId)]

  return sortBackgroundTasks(merged).slice(0, BACKGROUND_TASK_MAX_ITEMS)

}



export const isBackgroundTaskRunning = (status) => {

  return BACKGROUND_RUNNING_STATUS_SET.has(String(status || '').toLowerCase())

}
