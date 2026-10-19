import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  ChevronDown,
  Loader2,
  Pause,
  Play,
  QrCode,
  RefreshCcw,
  X
} from 'lucide-react'
import { AccountChip, Input, PageHeader, Toggle, useRuntimeProfile, useToast } from '../components'
import WorkspaceTabs from '../components/WorkspaceTabs'
import useWorkspaceTab from '../components/useWorkspaceTab'
import { api } from '../utils/api'
import { removeToken } from '../utils/auth'
import {
  applyCourseProgressToTaskRecords,
  applyTaskActionToRecords,
  groupVideosByChapter,
  getZhihuishuCourseId,
  TERMINAL_ZHIHUISHU_TASK_STATUSES,
} from '../utils/zhihuishuTasks'

const QR_POLL_INTERVAL_MS = 2000
const DEFAULT_PROGRESS_POLL_SECONDS = 5
const MIN_PROGRESS_POLL_SECONDS = 2
const MAX_PROGRESS_POLL_SECONDS = 60
const SETTINGS_STORAGE_KEY = 'zhihuishu_page_settings_v1'
const ACTIVE_TASK_ID_STORAGE_KEY = 'zhihuishu_active_task_id_v1'
const ZHIHUISHU_API_BASE = '/course/zhihuishu'

const CARD_CLASS = 'rounded-2xl border border-border bg-surface p-5 shadow-sm sm:p-6'
const PANEL_CLASS = 'rounded-xl border border-border bg-surface-hover/40 p-4'
const ZHIHUISHU_TABS = [
  { id: 'courses', label: '课程' },
  { id: 'study', label: '学习配置' },
  { id: 'tasks', label: '任务' },
  { id: 'account', label: '账号' },
]
// Old links: 登录 and 状态与退出 became 账号; 设置 became the 默认设置
// section of 学习配置.
const ZHIHUISHU_TAB_ALIASES = { login: 'account', status: 'account', settings: 'study' }
const FIELD_CLASS =
  'w-full min-w-0 min-h-[44px] rounded-xl border border-border bg-surface px-4 py-2 text-text focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60'
const LABEL_CLASS = 'mb-2 block text-sm font-semibold text-text'
const BUTTON_CLASS =
  'inline-flex min-h-[44px] items-center justify-center gap-2 rounded-xl px-4 text-sm font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 disabled:cursor-not-allowed disabled:opacity-60'
const PRIMARY_BUTTON_CLASS = `${BUTTON_CLASS} bg-primary text-white hover:bg-primary/90`
const SECONDARY_BUTTON_CLASS = `${BUTTON_CLASS} border border-border bg-surface text-text hover:bg-surface-hover`
const GHOST_BUTTON_CLASS = `${BUTTON_CLASS} text-text-muted hover:bg-surface-hover hover:text-text`
const DANGER_BUTTON_CLASS = `${BUTTON_CLASS} border border-danger/40 text-danger hover:bg-danger/10`
const SPEED_OPTIONS = ['0.5', '1.0', '1.5', '2.0']

// The speed <select> uses one-decimal values ("1.0"), but the config API
// returns numbers, and JSON turns 1.0 into 1. Without this, "1" matches no
// option and the select shows 0.5x while tasks run at 1x.
const toSpeedOption = (value, fallback = '1.0') => {
  const speed = Number(value)
  return Number.isFinite(speed) && speed > 0 ? speed.toFixed(1) : fallback
}

const pickMessage = (payload) => {
  if (!payload) return ''
  return payload.message || payload.detail || payload.msg || payload.data?.message || payload.error?.message || ''
}

const clampPercentage = (value) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 0
  return Math.min(100, Math.max(0, parsed))
}

const parseCourseId = (value) => {
  if (!value && value !== 0) return ''
  return String(value)
}

const clampPollSeconds = (value) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return DEFAULT_PROGRESS_POLL_SECONDS
  return Math.min(MAX_PROGRESS_POLL_SECONDS, Math.max(MIN_PROGRESS_POLL_SECONDS, Math.floor(parsed)))
}

const parseList = (payload, ...keys) => {
  for (const key of keys) {
    const value = key ? payload?.[key] : payload
    if (Array.isArray(value)) return value
  }
  return []
}

const parseObject = (payload, ...keys) => {
  for (const key of keys) {
    const value = key ? payload?.[key] : payload
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return value
    }
  }
  return {}
}

const buildQuery = (query) => {
  const params = new URLSearchParams()
  Object.entries(query || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    params.set(key, String(value))
  })
  const search = params.toString()
  return search ? `?${search}` : ''
}

const toIso = (value) => {
  if (value === undefined || value === null || value === '') return ''
  if (typeof value === 'number') {
    const ms = value > 1e12 ? value : value * 1000
    return new Date(ms).toISOString()
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toISOString()
}

const normalizeCourseGroups = (payload) => {
  const rawGroups = parseList(payload, 'data', 'groups')
  if (rawGroups.length > 0 && rawGroups.every((item) => Array.isArray(item?.courses))) {
    return rawGroups.map((group, index) => ({
      group: group.group || group.name || `分组 ${index + 1}`,
      courses: Array.isArray(group.courses) ? group.courses : []
    }))
  }

  const courses = parseList(payload, 'data', 'courses')
  if (courses.length === 0) return []

  const grouped = new Map()
  courses.forEach((course) => {
    const key = String(course?.semesterName || course?.termName || course?.courseTypeName || '默认分组')
    if (!grouped.has(key)) grouped.set(key, [])
    grouped.get(key).push(course)
  })
  return Array.from(grouped.entries()).map(([group, list]) => ({ group, courses: list }))
}

const flattenGroups = (groups) => {
  return groups.flatMap((group) =>
    group.courses.map((course) => ({
      ...course,
      _groupName: group.group || '默认分组'
    }))
  )
}

const extractCourseStructure = (detail) => {
  const chapters = parseList(detail, 'chapters', 'chapterDtos', 'chapterList')
  if (chapters.length > 0) {
    return chapters.map((chapter, index) => ({
      id: parseCourseId(chapter?.chapterId || chapter?.id || `chapter-${index}`),
      title: chapter?.chapterName || chapter?.name || `章节 ${index + 1}`,
      videos: parseList(chapter, 'videoLearningDtos', 'videoDtos', 'videos')
    }))
  }

  const sections = parseList(detail, 'sections', 'units')
  if (sections.length > 0) {
    return sections.map((section, index) => ({
      id: parseCourseId(section?.id || `section-${index}`),
      title: section?.name || section?.title || `结构 ${index + 1}`,
      videos: parseList(section, 'videos', 'videoDtos')
    }))
  }

  return []
}

const flattenStructureVideos = (structure) => {
  const result = []
  structure.forEach((section, sectionIndex) => {
    const videos = Array.isArray(section?.videos) ? section.videos : []
    videos.forEach((video, videoIndex) => {
      result.push({
        id: parseCourseId(video?.videoId || video?.id || `${sectionIndex + 1}-${videoIndex + 1}`),
        title: video?.videoName || video?.name || video?.title || `视频 ${result.length + 1}`,
        status: video?.status || 'pending',
        sectionTitle: section.title
      })
    })
  })
  return result
}

const normalizeTaskRecord = (payload, fallback = {}) => {
  const taskId = parseCourseId(payload?.task_id || payload?.taskId || fallback.taskId)
  if (!taskId) return null

  const nestedProgress = parseObject(payload?.progress, '')
  const fallbackProgress = parseObject(fallback?.progress, '')
  const total = Number(payload?.total ?? nestedProgress?.total ?? fallback.total ?? fallbackProgress?.total ?? 0)
  const completed = Number(payload?.completed ?? nestedProgress?.completed ?? fallback.completed ?? fallbackProgress?.completed ?? 0)
  const failed = Number(payload?.failed ?? nestedProgress?.failed ?? fallback.failed ?? fallbackProgress?.failed ?? 0)
  const percentage = Number(payload?.percentage ?? nestedProgress?.percentage ?? fallback.percentage ?? fallbackProgress?.percentage ?? 0)
  const status = String(payload?.status || nestedProgress?.status || fallback.status || fallbackProgress?.status || 'unknown')
  const message = payload?.message || nestedProgress?.message || fallback.message || fallbackProgress?.message || ''
  const currentTask =
    payload?.current_video ||
    payload?.currentTask ||
    nestedProgress?.current_video ||
    nestedProgress?.currentTask ||
    fallback.currentTask ||
    fallbackProgress?.current_video ||
    fallbackProgress?.currentTask ||
    ''

  return {
    taskId,
    taskType: payload?.task_type || payload?.taskType || fallback.taskType || 'course',
    courseId: getZhihuishuCourseId(payload) || getZhihuishuCourseId(fallback),
    courseName: payload?.course_name || payload?.courseName || fallback.courseName || '',
    status,
    message,
    currentTask,
    total: Number.isFinite(total) ? total : 0,
    completed: Number.isFinite(completed) ? completed : 0,
    failed: Number.isFinite(failed) ? failed : 0,
    percentage: Number.isFinite(percentage) ? percentage : 0,
    videos: Array.isArray(payload?.videos) ? payload.videos : (Array.isArray(fallback.videos) ? fallback.videos : []),
    progress: {
      ...fallbackProgress,
      ...nestedProgress,
      status,
      message,
      current_video: currentTask,
      total: Number.isFinite(total) ? total : 0,
      completed: Number.isFinite(completed) ? completed : 0,
      failed: Number.isFinite(failed) ? failed : 0,
      percentage: Number.isFinite(percentage) ? percentage : 0
    },
    startedAt: toIso(payload?.created_at || fallback.startedAt || Date.now()),
    updatedAt: toIso(payload?.updated_at || fallback.updatedAt || Date.now()),
    raw: payload
  }
}

export default function Zhihuishu() {
  const navigate = useNavigate()
  const qrPollRef = useRef(null)
  const qrGenerationRef = useRef(0)
  const qrSessionOwnerRef = useRef({ generation: 0, sessionId: '' })
  const qrPollsInFlightRef = useRef(new Map())
  const progressPollRef = useRef(null)
  const mountedRef = useRef(false)
  const coursesRef = useRef([])
  const selectedCourseIdRef = useRef('')
  const courseViewCourseIdRef = useRef('')
  const courseViewGenerationRef = useRef(0)
  const courseDetailRequestRef = useRef(0)
  const videosRequestRef = useRef(0)
  const chaptersRequestRef = useRef(0)
  const endChapterByCourseRef = useRef({})
  const progressRequestRef = useRef(0)
  const taskRecordsRef = useRef([])
  const activeTaskIdRef = useRef('')
  const taskViewTargetRef = useRef('')
  const taskViewGenerationRef = useRef(0)
  const taskSessionGenerationRef = useRef(0)
  const taskRequestGenerationRef = useRef(new Map())
  const taskRequestsInFlightRef = useRef(new Map())
  const fetchTaskDetailRef = useRef(null)
  const bootstrapStartedRef = useRef(false)
  const activeTaskStorageReadyRef = useRef(false)

  const { isLocal } = useRuntimeProfile()
  const toast = useToast()

  const [booting, setBooting] = useState(true)
  const [zhihuishuLoggedIn, setZhihuishuLoggedIn] = useState(false)
  // Only known after a password login; the status API does not name the user.
  const [loggedInAccount, setLoggedInAccount] = useState('')
  const [activeTab, setActiveTab] = useWorkspaceTab(
    ZHIHUISHU_TABS,
    zhihuishuLoggedIn ? 'courses' : 'account',
    ZHIHUISHU_TAB_ALIASES,
  )
  const [searchParams] = useSearchParams()
  const [defaultsOpen, setDefaultsOpen] = useState(() => searchParams.get('tab') === 'settings')

  const [loginMethod, setLoginMethod] = useState('qr')

  const [qrSessionId, setQrSessionId] = useState('')
  const [qrCode, setQrCode] = useState('')
  const [qrStatus, setQrStatus] = useState('idle')
  const [qrMessage, setQrMessage] = useState('')
  const [qrLoading, setQrLoading] = useState(false)
  const [qrError, setQrError] = useState('')

  const [passwordForm, setPasswordForm] = useState({ username: '', password: '' })
  const [passwordLoading, setPasswordLoading] = useState(false)

  const [courseGroups, setCourseGroups] = useState([])
  const [courses, setCourses] = useState([])
  const [coursesLoading, setCoursesLoading] = useState(false)
  const [selectedCourseId, setSelectedCourseId] = useState('')
  const [courseDetail, setCourseDetail] = useState(null)
  const [courseDetailLoading, setCourseDetailLoading] = useState(false)
  const [courseStructure, setCourseStructure] = useState([])

  const [videos, setVideos] = useState([])
  const [videosLoading, setVideosLoading] = useState(false)
  // Both keyed by course id, so a choice survives switching courses.
  // chaptersByCourse comes from the video list; endChapterByCourse holds the
  // last chapter to study (absent = whole course).
  const [chaptersByCourse, setChaptersByCourse] = useState({})
  const [endChapterByCourse, setEndChapterByCourse] = useState({})
  const [chaptersLoading, setChaptersLoading] = useState(false)

  const [progress, setProgress] = useState(null)
  const [progressLoading, setProgressLoading] = useState(false)

  const [startLoadingType, setStartLoadingType] = useState('')
  const [taskActionLoading, setTaskActionLoading] = useState('')
  const [taskItemActionLoading, setTaskItemActionLoading] = useState('')
  const [taskRecords, setTaskRecords] = useState([])
  const [activeTaskId, setActiveTaskId] = useState('')
  const [settingsSaving, setSettingsSaving] = useState(false)

  useEffect(() => {
    mountedRef.current = true
    const qrPollsInFlight = qrPollsInFlightRef.current
    return () => {
      mountedRef.current = false
      qrGenerationRef.current += 1
      qrSessionOwnerRef.current = {
        generation: qrGenerationRef.current,
        sessionId: ''
      }
      qrPollsInFlight.clear()
      if (qrPollRef.current) {
        clearInterval(qrPollRef.current)
        qrPollRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    coursesRef.current = courses
  }, [courses])

  useEffect(() => {
    taskRecordsRef.current = taskRecords
  }, [taskRecords])

  useEffect(() => {
    endChapterByCourseRef.current = endChapterByCourse
  }, [endChapterByCourse])

  const [settings, setSettings] = useState({
    speed: '1.0',
    autoAnswer: true,
    progressPollSeconds: DEFAULT_PROGRESS_POLL_SECONDS
  })

  const setNoticeMessage = useCallback(
    (type, message) => {
      if (!message) return
      toast.notify(type, message)
    },
    [toast]
  )

  const stopQrPolling = useCallback(() => {
    if (qrPollRef.current) {
      clearInterval(qrPollRef.current)
      qrPollRef.current = null
    }
  }, [])

  const invalidateQrGeneration = useCallback(() => {
    const generation = qrGenerationRef.current + 1
    qrGenerationRef.current = generation
    qrSessionOwnerRef.current = { generation, sessionId: '' }
    qrPollsInFlightRef.current.clear()
    stopQrPolling()
    return generation
  }, [stopQrPolling])

  const abandonQrLoginIntent = useCallback(() => {
    invalidateQrGeneration()
    setQrSessionId('')
    setQrCode('')
    setQrStatus('idle')
    setQrMessage('')
    setQrError('')
    setQrLoading(false)
  }, [invalidateQrGeneration])

  const ownsQrSession = useCallback((generation, sessionId) => {
    const owner = qrSessionOwnerRef.current
    return mountedRef.current
      && qrGenerationRef.current === generation
      && owner.generation === generation
      && owner.sessionId === sessionId
  }, [])

  const stopProgressPolling = useCallback(() => {
    if (progressPollRef.current) {
      clearInterval(progressPollRef.current)
      progressPollRef.current = null
    }
  }, [])

  const requestZhihuishuApi = useCallback(async (path, options = {}) => {
    return api(`${ZHIHUISHU_API_BASE}${path}`, options)
  }, [])

  const selectCourse = useCallback((courseId) => {
    const normalizedCourseId = parseCourseId(courseId)
    selectedCourseIdRef.current = normalizedCourseId
    if (courseViewCourseIdRef.current !== normalizedCourseId) {
      courseViewCourseIdRef.current = normalizedCourseId
      courseViewGenerationRef.current += 1
    }
    setSelectedCourseId(normalizedCourseId)
  }, [])

  const beginTaskViewIntent = useCallback((taskId) => {
    taskViewGenerationRef.current += 1
    taskViewTargetRef.current = parseCourseId(taskId)
    return taskViewGenerationRef.current
  }, [])

  const selectActiveTask = useCallback((taskId) => {
    const normalizedTaskId = parseCourseId(taskId)
    beginTaskViewIntent(normalizedTaskId)
    activeTaskIdRef.current = normalizedTaskId
    setActiveTaskId(normalizedTaskId)
  }, [beginTaskViewIntent])

  const upsertTaskRecord = useCallback((nextTask, canWrite) => {
    if (!nextTask?.taskId) return
    setTaskRecords((prev) => {
      if (canWrite && !canWrite()) return prev
      const index = prev.findIndex((task) => task.taskId === nextTask.taskId)
      if (index === -1) {
        const next = [nextTask, ...prev].slice(0, 20)
        taskRecordsRef.current = next
        return next
      }
      const copy = [...prev]
      copy[index] = { ...copy[index], ...nextTask }
      taskRecordsRef.current = copy
      return copy
    })
  }, [])

  const mergeTaskRecords = useCallback((nextTasks, replaceAll = false, canWrite) => {
    setTaskRecords((prev) => {
      if (canWrite && !canWrite()) return prev
      const base = replaceAll ? [] : prev
      const map = new Map(base.map((task) => [task.taskId, task]))
      nextTasks.forEach((task) => {
        if (!task?.taskId) return
        map.set(task.taskId, { ...(map.get(task.taskId) || {}), ...task })
      })
      const next = Array.from(map.values()).slice(0, 50)
      taskRecordsRef.current = next
      return next
    })
  }, [])

  const loadSettingsFromStorage = useCallback(() => {
    try {
      const raw = localStorage.getItem(SETTINGS_STORAGE_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw)
      setSettings((prev) => ({
        ...prev,
        speed: toSpeedOption(parsed.speed, prev.speed),
        autoAnswer: typeof parsed.autoAnswer === 'boolean' ? parsed.autoAnswer : prev.autoAnswer,
        progressPollSeconds: clampPollSeconds(parsed.progressPollSeconds ?? prev.progressPollSeconds)
      }))
    } catch (err) {
      console.warn('Failed to load zhihuishu settings:', err)
    }
  }, [])

  const saveSettingsToStorage = useCallback((nextSettings) => {
    const merged = {
      speed: String(nextSettings.speed || '1.0'),
      autoAnswer: Boolean(nextSettings.autoAnswer),
      progressPollSeconds: clampPollSeconds(nextSettings.progressPollSeconds)
    }

    try {
      localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(merged))
      return true
    } catch (_) {
      return false
    }
  }, [])

  const readActiveTaskIdFromStorage = useCallback(() => {
    try {
      return parseCourseId(localStorage.getItem(ACTIVE_TASK_ID_STORAGE_KEY))
    } catch (err) {
      console.warn('Failed to load active task id:', err)
      return ''
    }
  }, [])

  const saveActiveTaskIdToStorage = useCallback((nextTaskId) => {
    const normalizedTaskId = parseCourseId(nextTaskId)
    try {
      if (normalizedTaskId) {
        localStorage.setItem(ACTIVE_TASK_ID_STORAGE_KEY, normalizedTaskId)
      } else {
        localStorage.removeItem(ACTIVE_TASK_ID_STORAGE_KEY)
      }
    } catch (err) {
      console.warn('Failed to save active task id:', err)
    }
  }, [])

  const loadConfigFromBackend = useCallback(async (silent = true, canWrite = () => true) => {
    if (!canWrite()) return false
    try {
      const resp = await requestZhihuishuApi('/config', { method: 'GET' })
      if (!canWrite()) return false
      const config = parseObject(resp, 'data', 'config')
      setSettings((prev) => {
        if (!canWrite()) return prev
        const merged = {
          ...prev,
          speed: toSpeedOption(config?.speed, prev.speed),
          autoAnswer: typeof config?.auto_answer === 'boolean'
            ? config.auto_answer
            : (typeof config?.autoAnswer === 'boolean' ? config.autoAnswer : prev.autoAnswer)
        }
        if (!canWrite()) return prev
        saveSettingsToStorage(merged)
        return merged
      })
      if (!silent && canWrite()) {
        setNoticeMessage('success', pickMessage(resp) || '配置已同步。')
      }
      return true
    } catch (err) {
      if (!canWrite()) return false
      if (!silent) {
        setNoticeMessage('info', '配置同步失败，已使用本地配置。')
      }
      return false
    }
  }, [requestZhihuishuApi, saveSettingsToStorage, setNoticeMessage])

  const saveSettings = useCallback(async (nextSettings) => {
    const merged = {
      speed: String(nextSettings.speed || '1.0'),
      autoAnswer: Boolean(nextSettings.autoAnswer),
      progressPollSeconds: clampPollSeconds(nextSettings.progressPollSeconds)
    }

    setSettings(merged)
    setSettingsSaving(true)
    const savedToStorage = saveSettingsToStorage(merged)
    try {
      const resp = await requestZhihuishuApi('/config', {
        method: 'PUT',
        body: JSON.stringify({
          speed: Number(merged.speed) || 1,
          auto_answer: merged.autoAnswer
        })
      })
      setNoticeMessage('success', pickMessage(resp) || '配置已保存。')
    } catch (err) {
      if (savedToStorage) {
        setNoticeMessage('info', '配置同步失败，已保存到本地。')
      } else {
        setNoticeMessage('error', err.message || '配置保存失败。')
      }
    } finally {
      setSettingsSaving(false)
    }
  }, [requestZhihuishuApi, saveSettingsToStorage, setNoticeMessage])

  const applyGroupedCourses = useCallback((groups) => {
    setCourseGroups(groups)
    const flatCourses = flattenGroups(groups)
    coursesRef.current = flatCourses
    setCourses(flatCourses)
    const currentCourseId = selectedCourseIdRef.current
    const nextCourseId = currentCourseId && flatCourses.some(
      (course) => getZhihuishuCourseId(course) === currentCourseId,
    )
      ? currentCourseId
      : getZhihuishuCourseId(flatCourses[0])
    selectCourse(nextCourseId)
    return flatCourses
  }, [selectCourse])

  const loadCourseDetail = useCallback(async (courseId, silent = false) => {
    if (!courseId) return null

    const requestGeneration = courseDetailRequestRef.current + 1
    courseDetailRequestRef.current = requestGeneration
    const viewGeneration = courseViewGenerationRef.current
    const isCurrent = () => (
      mountedRef.current &&
      courseDetailRequestRef.current === requestGeneration &&
      courseViewGenerationRef.current === viewGeneration &&
      selectedCourseIdRef.current === courseId
    )

    setCourseDetailLoading((current) => (isCurrent() ? true : current))
    try {
      const resp = await requestZhihuishuApi(`/courses/${encodeURIComponent(courseId)}`, { method: 'GET' })
      if (!isCurrent()) return null
      const detail = parseObject(resp, 'data')
      setCourseDetail((current) => (isCurrent() ? detail : current))

      const structure = extractCourseStructure(detail)
      setCourseStructure((current) => (isCurrent() ? structure : current))

      const detailVideos = flattenStructureVideos(structure)
      if (detailVideos.length > 0) {
        setVideos((current) => (isCurrent() ? detailVideos : current))
      }

      if (!silent && isCurrent()) {
        setNoticeMessage('success', pickMessage(resp) || '课程详情已更新。')
      }
      return detail
    } catch (err) {
      if (!isCurrent()) return null
      const fallback = coursesRef.current.find(
        (course) => getZhihuishuCourseId(course) === courseId,
      ) || null
      setCourseDetail((current) => (isCurrent() ? fallback : current))
      setCourseStructure((current) => (isCurrent() ? [] : current))
      if (!silent && isCurrent()) {
        setNoticeMessage('info', '课程详情加载失败，已使用课程列表数据。')
      }
      return fallback
    } finally {
      setCourseDetailLoading((current) => (isCurrent() ? false : current))
    }
  }, [requestZhihuishuApi, setNoticeMessage])

  // Stores a course's chapters. A chosen end chapter that is no longer in the
  // list is dropped, and the user is told, since the course would otherwise be
  // studied in full without them noticing.
  const storeChapters = useCallback((courseId, videoChapters) => {
    setChaptersByCourse((prev) => ({ ...prev, [courseId]: videoChapters }))
    const chosen = endChapterByCourseRef.current[courseId]
    if (chosen && !videoChapters.some((chapter) => chapter.id === chosen)) {
      setEndChapterByCourse((prev) => {
        const next = { ...prev }
        delete next[courseId]
        return next
      })
      setNoticeMessage('info', '之前选的最后一章已不在这门课里，已改回「全部章节」，请重新选择。')
    }
  }, [setNoticeMessage])

  // Chapters always come from the video list: its chapter ids are the ones the
  // task start endpoint matches end_chapter_id against. They are stored per
  // course, so a reply that lands after a course switch is still kept.
  const loadChapters = useCallback(async (courseId) => {
    if (!courseId) return
    const requestGeneration = chaptersRequestRef.current + 1
    chaptersRequestRef.current = requestGeneration
    const isCurrent = () => mountedRef.current && chaptersRequestRef.current === requestGeneration

    setChaptersLoading(true)
    try {
      const resp = await api(`${ZHIHUISHU_API_BASE}/videos/${encodeURIComponent(courseId)}`, { method: 'GET' })
      if (!isCurrent()) return
      const videoChapters = groupVideosByChapter(parseList(resp, 'data', 'videos'))
      storeChapters(courseId, videoChapters)
      if (videoChapters.length === 0) {
        setNoticeMessage('info', '没有读到这门课的章节，只能学完整门课。')
      }
    } catch (err) {
      if (isCurrent()) {
        setNoticeMessage('error', err.message || '加载章节失败。')
      }
    } finally {
      if (isCurrent()) setChaptersLoading(false)
    }
  }, [setNoticeMessage, storeChapters])

  const loadVideos = useCallback(async (courseId) => {
    if (!courseId) {
      setNoticeMessage('error', '请先选择课程。')
      return
    }

    const requestGeneration = videosRequestRef.current + 1
    videosRequestRef.current = requestGeneration
    const viewGeneration = courseViewGenerationRef.current
    const isCurrent = () => (
      mountedRef.current &&
      videosRequestRef.current === requestGeneration &&
      courseViewGenerationRef.current === viewGeneration &&
      selectedCourseIdRef.current === courseId
    )

    setVideosLoading((current) => (isCurrent() ? true : current))
    try {
      const detail = await loadCourseDetail(courseId, true)
      if (!isCurrent()) return null
      const structure = extractCourseStructure(detail || {})
      const detailVideos = flattenStructureVideos(structure)

      if (detailVideos.length > 0) {
        setCourseStructure((current) => (isCurrent() ? structure : current))
        setVideos((current) => (isCurrent() ? detailVideos : current))
        if (isCurrent()) {
          setNoticeMessage('success', `已从课程结构加载 ${detailVideos.length} 个视频。`)
        }
        return
      }

      const legacyResp = await api(`${ZHIHUISHU_API_BASE}/videos/${encodeURIComponent(courseId)}`, { method: 'GET' })
      if (!isCurrent()) return null
      const legacyVideos = parseList(legacyResp, 'data', 'videos')
      setVideos((current) => (isCurrent() ? legacyVideos : current))
      const videoChapters = groupVideosByChapter(legacyVideos)
      if (isCurrent()) storeChapters(courseId, videoChapters)
      if (legacyVideos.length > 0) {
        setCourseStructure((current) => {
          if (!isCurrent() || current.length > 0) return current
          if (videoChapters.length > 0) {
            return videoChapters
          }
          return [{
            id: `${courseId}-legacy`,
            title: '视频任务',
            videos: legacyVideos
          }]
        })
      }
      if (isCurrent()) {
        setNoticeMessage('success', `已加载 ${legacyVideos.length} 个视频任务。`)
      }
    } catch (err) {
      if (isCurrent()) {
        setNoticeMessage('error', err.message || '加载视频列表失败。')
      }
    } finally {
      setVideosLoading((current) => (isCurrent() ? false : current))
    }
  }, [loadCourseDetail, setNoticeMessage, storeChapters])

  const loadCourses = useCallback(async (silent = false, canWrite = () => true) => {
    if (!canWrite()) return []
    setCoursesLoading(true)
    try {
      let groups = []
      try {
        const groupedResp = await requestZhihuishuApi('/courses/grouped', { method: 'GET' })
        if (!canWrite()) return []
        groups = normalizeCourseGroups(groupedResp)
      } catch (_) {
        if (!canWrite()) return []
        const legacyResp = await api(`${ZHIHUISHU_API_BASE}/courses`, { method: 'GET' })
        if (!canWrite()) return []
        groups = normalizeCourseGroups(legacyResp)
      }

      if (!canWrite()) return []
      const flatCourses = applyGroupedCourses(groups)
      if (!canWrite()) return []
      setZhihuishuLoggedIn(true)
      if (!silent && canWrite()) {
        setNoticeMessage(
          'success',
          flatCourses.length > 0 ? '分组课程加载完成。' : '暂无课程数据。'
        )
      }
      return flatCourses
    } catch (err) {
      if (!canWrite()) return []
      if (!silent) {
        setNoticeMessage('error', err.message || '加载课程失败。')
      }
      return []
    } finally {
      if (canWrite()) {
        setCoursesLoading(false)
      }
    }
  }, [applyGroupedCourses, requestZhihuishuApi, setNoticeMessage])

  const loadCourseProgress = useCallback(async (courseId, silent = true) => {
    if (!courseId) return null

    const requestGeneration = progressRequestRef.current + 1
    progressRequestRef.current = requestGeneration
    const viewGeneration = courseViewGenerationRef.current
    const isCurrent = () => (
      mountedRef.current &&
      progressRequestRef.current === requestGeneration &&
      courseViewGenerationRef.current === viewGeneration &&
      selectedCourseIdRef.current === courseId
    )

    setProgressLoading((current) => (isCurrent() ? true : current))
    try {
      const resp = await api(`${ZHIHUISHU_API_BASE}/progress/${encodeURIComponent(courseId)}`, { method: 'GET' })
      if (!isCurrent()) return null
      const progressPayload = parseObject(resp, 'data', '')
      const statusValue = String(progressPayload?.status || resp?.status || 'running')
      const messageValue = progressPayload?.message || resp?.message || '进度已更新'
      const currentVideo = progressPayload?.current_video || progressPayload?.currentTask || ''

      const normalizedProgress = {
        ...progressPayload,
        status: statusValue,
        message: messageValue,
        current_video: currentVideo
      }

      setProgress((current) => (isCurrent() ? normalizedProgress : current))
      setTaskRecords((prev) => {
        if (!isCurrent()) return prev
        const next = applyCourseProgressToTaskRecords(prev, {
          courseId,
          activeTaskId: activeTaskIdRef.current,
          progress: normalizedProgress,
          updatedAt: new Date().toISOString()
        })
        taskRecordsRef.current = next
        return next
      })
      if (!silent && isCurrent()) {
        setNoticeMessage('success', '课程进度已刷新。')
      }
      return progressPayload
    } catch (err) {
      if (!silent && isCurrent()) {
        setNoticeMessage('error', err.message || '查询进度失败。')
      }
      return null
    } finally {
      setProgressLoading((current) => (isCurrent() ? false : current))
    }
  }, [setNoticeMessage])

  const fetchTaskDetail = useCallback(async (taskId, silent = false) => {
    if (!taskId) return null

    const requestsInFlight = taskRequestsInFlightRef.current.get(taskId)
    if (silent && requestsInFlight?.size) return null

    const requestGeneration = (taskRequestGenerationRef.current.get(taskId) || 0) + 1
    taskRequestGenerationRef.current.set(taskId, requestGeneration)
    const nextRequestsInFlight = requestsInFlight || new Set()
    nextRequestsInFlight.add(requestGeneration)
    taskRequestsInFlightRef.current.set(taskId, nextRequestsInFlight)

    const viewGeneration = silent
      ? taskViewGenerationRef.current
      : beginTaskViewIntent(taskId)
    const sessionGeneration = taskSessionGenerationRef.current
    const isLatestTaskRequest = () => (
      mountedRef.current &&
      taskSessionGenerationRef.current === sessionGeneration &&
      taskRequestGenerationRef.current.get(taskId) === requestGeneration
    )
    const canWriteTaskView = () => (
      isLatestTaskRequest() &&
      taskViewGenerationRef.current === viewGeneration &&
      taskViewTargetRef.current === taskId
    )

    try {
      const resp = await requestZhihuishuApi(`/tasks/${taskId}`, { method: 'GET' })
      if (!isLatestTaskRequest()) return null
      const detail = parseObject(resp, 'data')
      const previous = taskRecordsRef.current.find((task) => task.taskId === taskId) || {}
      const normalized = normalizeTaskRecord(detail, previous)
      if (!normalized) return null

      // Announce terminal transitions even during silent polling — otherwise a
      // task that finishes or fails in the background gives the user no signal.
      // Require a real prior record (previous.taskId) so restoring an already-
      // finished task on page load doesn't fire a stale "completed" toast.
      if (
        previous.taskId &&
        TERMINAL_ZHIHUISHU_TASK_STATUSES.has(normalized.status) &&
        !TERMINAL_ZHIHUISHU_TASK_STATUSES.has(previous.status)
      ) {
        const courseLabel = normalized.courseName || '智慧树任务'
        if (normalized.status === 'completed') {
          setNoticeMessage('success', `「${courseLabel}」学习完成。`)
        } else if (normalized.status === 'cancelled') {
          setNoticeMessage('info', `「${courseLabel}」任务已取消。`)
        } else {
          setNoticeMessage('error', `「${courseLabel}」任务${normalized.status === 'failed' ? '失败' : '异常'}：${normalized.message || '请查看任务详情。'}`)
        }
      }

      const fallbackCourse = coursesRef.current.find(
        (course) => getZhihuishuCourseId(course) === normalized.courseId,
      )
      if (!normalized.courseName && fallbackCourse) {
        normalized.courseName = fallbackCourse.courseName || fallbackCourse.name || fallbackCourse.title || normalized.courseId
      }

      upsertTaskRecord(normalized, isLatestTaskRequest)
      if (normalized.courseId === selectedCourseIdRef.current && canWriteTaskView()) {
        setProgress((current) => (canWriteTaskView() ? {
          status: normalized.status,
          message: normalized.message,
          current_video: normalized.currentTask,
          total: normalized.total,
          completed: normalized.completed,
          failed: normalized.failed,
          percentage: normalized.percentage
        } : current))
      }
      if (
        Array.isArray(normalized.videos) &&
        normalized.videos.length > 0 &&
        normalized.courseId === selectedCourseIdRef.current &&
        canWriteTaskView()
      ) {
        const taskVideos = normalized.videos.map((video, index) => ({
          id: parseCourseId(video?.id || video?.videoId || index + 1),
          title: video?.title || video?.name || video?.videoName || `视频 ${index + 1}`,
          status: video?.status || 'pending'
        }))
        setVideos((current) => (canWriteTaskView() ? taskVideos : current))
      }
      if (!silent && canWriteTaskView()) {
        setNoticeMessage('success', pickMessage(resp) || '任务详情已刷新。')
      }
      if (canWriteTaskView()) {
        activeTaskIdRef.current = normalized.taskId
        setActiveTaskId(normalized.taskId)
        if (TERMINAL_ZHIHUISHU_TASK_STATUSES.has(normalized.status)) {
          stopProgressPolling()
        }
      }
      return normalized
    } catch (err) {
      if (!isLatestTaskRequest()) return null
      const fallback = taskRecordsRef.current.find((task) => task.taskId === taskId)
      if (fallback?.courseId) {
        await loadCourseProgress(fallback.courseId, true)
      }
      if (!silent && canWriteTaskView()) {
        setNoticeMessage('error', err.message || '获取任务详情失败。')
        beginTaskViewIntent(activeTaskIdRef.current)
      }
      return null
    } finally {
      const pendingRequests = taskRequestsInFlightRef.current.get(taskId)
      if (pendingRequests) {
        pendingRequests.delete(requestGeneration)
        if (pendingRequests.size === 0) {
          taskRequestsInFlightRef.current.delete(taskId)
        }
      }
    }
  }, [beginTaskViewIntent, loadCourseProgress, requestZhihuishuApi, setNoticeMessage, stopProgressPolling, upsertTaskRecord])

  const fetchTaskList = useCallback(async ({ silent = false, taskType, courseId, preferredTaskId, canWrite = () => true } = {}) => {
    if (!canWrite()) return []
    try {
      const query = buildQuery({
        task_type: taskType,
        course_id: courseId
      })
      const resp = await requestZhihuishuApi(`/tasks${query}`, { method: 'GET' })
      if (!canWrite()) return []
      const tasks = parseList(resp, 'data', 'tasks')
      const normalized = tasks
        .map((task) => {
          const item = normalizeTaskRecord(task)
          if (!item) return null
          const linkedCourse = coursesRef.current.find(
            (course) => getZhihuishuCourseId(course) === item.courseId,
          )
          if (!item.courseName && linkedCourse) {
            item.courseName = linkedCourse.courseName || linkedCourse.name || linkedCourse.title || item.courseId
          }
          return item
        })
        .filter(Boolean)

      if (!canWrite()) return []
      mergeTaskRecords(normalized, true, canWrite)
      const preferredId = parseCourseId(preferredTaskId)
      if (canWrite() && preferredId && normalized.some((task) => task.taskId === preferredId)) {
        selectActiveTask(preferredId)
      } else if (canWrite() && !activeTaskIdRef.current && normalized[0]?.taskId) {
        selectActiveTask(normalized[0].taskId)
      }
      if (!silent && canWrite()) {
        setNoticeMessage('success', normalized.length > 0 ? '任务列表已刷新。' : '暂无任务记录。')
      }
      return normalized
    } catch (err) {
      if (!canWrite()) return []
      if (!silent) {
        setNoticeMessage('error', err.message || '加载任务列表失败。')
      }
      return []
    }
  }, [mergeTaskRecords, requestZhihuishuApi, selectActiveTask, setNoticeMessage])

  const refreshTaskList = useCallback(async () => {
    const loadedTasks = await fetchTaskList({ silent: true })
    if (loadedTasks.length === 0 && selectedCourseId) {
      await loadCourseProgress(selectedCourseId, true)
    }
    setNoticeMessage('success', '任务状态已刷新。')
  }, [fetchTaskList, loadCourseProgress, selectedCourseId, setNoticeMessage])

  const chapterScope = useMemo(() => {
    const chapters = chaptersByCourse[selectedCourseId] || []
    const endChapterId = endChapterByCourse[selectedCourseId] || ''
    const endIndex = endChapterId ? chapters.findIndex((chapter) => chapter.id === endChapterId) : -1
    let hint = '默认学完整门课。想只学一部分，先加载章节再选。'
    if (endIndex >= 0) {
      const videoCount = chapters.slice(0, endIndex + 1).reduce((sum, chapter) => sum + chapter.videoCount, 0)
      const skipped = chapters.length - endIndex - 1
      hint = `只学到第 ${endIndex + 1} 章（含），共 ${videoCount} 个视频${skipped > 0 ? `；后面 ${skipped} 章不学` : ''}。`
    } else if (chapters.length > 0) {
      hint = '默认学完整门课；选一章后只学到这一章（含）。'
    }
    return { chapters, endChapterId: endIndex >= 0 ? endChapterId : '', hint }
  }, [chaptersByCourse, endChapterByCourse, selectedCourseId])

  const setEndChapter = useCallback((chapterId) => {
    if (!selectedCourseId) return
    setEndChapterByCourse((prev) => {
      const next = { ...prev }
      if (chapterId) next[selectedCourseId] = chapterId
      else delete next[selectedCourseId]
      return next
    })
  }, [selectedCourseId])

  const startCourseTask = useCallback(async (taskType = 'course') => {
    if (!selectedCourseId || startLoadingType) {
      if (!selectedCourseId) {
        setNoticeMessage('error', '请先选择课程。')
      }
      return
    }

    setStartLoadingType(taskType)
    const endChapterId = chapterScope.endChapterId
    const payload = {
      course_id: selectedCourseId,
      speed: Number(settings.speed) || 1,
      auto_answer: settings.autoAnswer,
      ...(endChapterId ? { end_chapter_id: endChapterId } : {})
    }

    try {
      let resp
      try {
        resp = await requestZhihuishuApi(taskType === 'ai-course' ? '/tasks/ai-course' : '/tasks/course', {
          method: 'POST',
          body: JSON.stringify(payload)
        })
      } catch (err) {
        if (err?.status !== 404 && err?.status !== 405) {
          throw err
        }
        resp = await api(`${ZHIHUISHU_API_BASE}/course/start`, {
          method: 'POST',
          body: JSON.stringify(payload)
        })
      }

      const taskId = parseCourseId(resp?.task_id || resp?.data?.task_id)
      if (!taskId) {
        throw new Error('服务端未返回有效任务编号，任务未启动。')
      }
      const selectedCourse = courses.find((course) => getZhihuishuCourseId(course) === selectedCourseId)
      const courseName = selectedCourse?.courseName || selectedCourse?.name || selectedCourse?.title || selectedCourseId

      upsertTaskRecord({
        taskId,
        taskType,
        courseId: selectedCourseId,
        courseName,
        status: 'running',
        message: pickMessage(resp) || '课程任务已启动。',
        currentTask: '',
        progress: null,
        startedAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
      })

      selectActiveTask(taskId)
      setActiveTab('tasks')
      setNoticeMessage('success', pickMessage(resp) || '课程任务已启动。')
      await fetchTaskDetail(taskId, true)
    } catch (err) {
      setNoticeMessage('error', err.message || '启动课程失败。')
    } finally {
      setStartLoadingType('')
    }
  }, [chapterScope.endChapterId, courses, fetchTaskDetail, requestZhihuishuApi, selectActiveTask, selectedCourseId, setNoticeMessage, settings.autoAnswer, settings.speed, startLoadingType, upsertTaskRecord, setActiveTab])

  const cancelTaskById = useCallback(async (taskId) => {
    if (!taskId || taskActionLoading || taskItemActionLoading) return
    if (!window.confirm('确定要取消该任务吗？此操作不可撤销。')) return
    setTaskItemActionLoading(taskId)
    try {
      const resp = await requestZhihuishuApi(`/tasks/${taskId}/cancel`, { method: 'POST' })
      const current = taskRecordsRef.current.find((task) => task.taskId === taskId) || {}
      upsertTaskRecord({
        ...current,
        taskId,
        status: 'cancelled',
        message: pickMessage(resp) || '任务已取消。',
        updatedAt: new Date().toISOString()
      })
      if (taskId === activeTaskId) {
        setProgress(null)
      }
      setNoticeMessage('success', pickMessage(resp) || '任务已取消。')
    } catch (err) {
      setNoticeMessage('error', err.message || '取消任务失败。')
    } finally {
      setTaskItemActionLoading('')
    }
  }, [activeTaskId, requestZhihuishuApi, setNoticeMessage, taskActionLoading, taskItemActionLoading, upsertTaskRecord])

  const pauseTask = async () => {
    if (taskActionLoading) return
    setTaskActionLoading('pause')

    try {
      const resp = await api(`${ZHIHUISHU_API_BASE}/pause`, { method: 'POST' })
      setTaskRecords((prev) => applyTaskActionToRecords(prev, {
        action: 'pause',
        message: pickMessage(resp) || '任务已暂停。',
        updatedAt: new Date().toISOString()
      }))
      stopProgressPolling()
      setNoticeMessage('success', pickMessage(resp) || '任务已暂停。')
    } catch (err) {
      setNoticeMessage('error', err.message || '暂停任务失败。')
    } finally {
      setTaskActionLoading('')
    }
  }

  const resumeTask = async () => {
    if (taskActionLoading) return
    setTaskActionLoading('resume')

    try {
      const resp = await api(`${ZHIHUISHU_API_BASE}/resume`, { method: 'POST' })
      setTaskRecords((prev) => applyTaskActionToRecords(prev, {
        action: 'resume',
        message: pickMessage(resp) || '任务已恢复。',
        updatedAt: new Date().toISOString()
      }))
      setNoticeMessage('success', pickMessage(resp) || '任务已恢复。')
      await refreshTaskList()
    } catch (err) {
      setNoticeMessage('error', err.message || '恢复任务失败。')
    } finally {
      setTaskActionLoading('')
    }
  }

  const cancelTask = async () => {
    if (taskActionLoading) return
    if (!window.confirm('确定要取消当前所有进行中的任务吗？此操作不可撤销。')) return
    setTaskActionLoading('cancel')

    try {
      const resp = await api(`${ZHIHUISHU_API_BASE}/cancel`, { method: 'POST' })
      setTaskRecords((prev) => applyTaskActionToRecords(prev, {
        action: 'cancel',
        message: pickMessage(resp) || '任务已取消。',
        updatedAt: new Date().toISOString()
      }))
      selectActiveTask('')
      setProgress(null)
      stopProgressPolling()
      setNoticeMessage('success', pickMessage(resp) || '任务已取消。')
    } catch (err) {
      setNoticeMessage('error', err.message || '取消任务失败。')
    } finally {
      setTaskActionLoading('')
    }
  }

  const pollQrStatus = useCallback(async (sessionId, generation) => {
    if (!ownsQrSession(generation, sessionId)) return
    if (qrPollsInFlightRef.current.has(generation)) return
    qrPollsInFlightRef.current.set(generation, sessionId)

    try {
      const resp = await api(`${ZHIHUISHU_API_BASE}/login-status/${sessionId}`, { method: 'GET' })
      if (!ownsQrSession(generation, sessionId)) return

      const nextStatus = String(resp?.status || 'pending')
      setQrStatus(nextStatus)
      setQrMessage(resp?.message || '等待扫码')

      // The backend regenerates the QR image when the original expires; render the
      // refreshed code so a slow scan can still succeed. (F-qr-refresh)
      if (resp?.qr_code) {
        setQrCode((prev) => (prev === resp.qr_code ? prev : resp.qr_code))
      }

      if (nextStatus === 'success') {
        stopQrPolling()
        setZhihuishuLoggedIn(true)
        setNoticeMessage('success', '二维码登录成功，正在加载课程。')
        const canWrite = () => ownsQrSession(generation, sessionId)
        await Promise.all([
          loadCourses(true, canWrite),
          loadConfigFromBackend(true, canWrite),
          fetchTaskList({ silent: true, canWrite })
        ])
        if (!ownsQrSession(generation, sessionId)) return
      }
      if (nextStatus === 'failed') {
        stopQrPolling()
      }
    } catch (err) {
      if (!ownsQrSession(generation, sessionId)) return
      stopQrPolling()
      setQrStatus('failed')
      setQrError(err.message || '查询二维码状态失败。')
      setNoticeMessage('error', err.message || '查询二维码状态失败。')
    } finally {
      if (qrPollsInFlightRef.current.get(generation) === sessionId) {
        qrPollsInFlightRef.current.delete(generation)
      }
    }
  }, [fetchTaskList, loadConfigFromBackend, loadCourses, ownsQrSession, setNoticeMessage, stopQrPolling])

  const startQrLogin = useCallback(async () => {
    if (qrLoading) return

    const generation = invalidateQrGeneration()
    let ownerSessionId = ''
    setQrLoading(true)
    setQrError('')
    setQrStatus('loading')
    setQrMessage('正在生成二维码...')
    setNoticeMessage('info', '正在创建二维码登录会话。')

    try {
      const resp = await api(`${ZHIHUISHU_API_BASE}/qr-login`, { method: 'POST' })
      if (!ownsQrSession(generation, ownerSessionId)) return

      const nextSessionId = resp?.session_id
      const nextQrCode = resp?.qr_code
      if (!nextSessionId || !nextQrCode) {
        throw new Error('二维码登录响应无效。')
      }

      ownerSessionId = nextSessionId
      qrSessionOwnerRef.current = { generation, sessionId: nextSessionId }
      setQrSessionId(nextSessionId)
      setQrCode(nextQrCode)
      setQrStatus(String(resp?.status || 'pending'))
      setQrMessage(resp?.message || '请使用智慧树 App 扫码。')
      setNoticeMessage('success', '二维码已生成，请尽快扫码。')
    } catch (err) {
      if (!ownsQrSession(generation, ownerSessionId)) return
      const message = err.message || '创建二维码会话失败。'
      setQrStatus('failed')
      setQrError(message)
      setQrMessage(message)
      setNoticeMessage('error', message)
    } finally {
      if (ownsQrSession(generation, ownerSessionId)) {
        setQrLoading(false)
      }
    }
  }, [invalidateQrGeneration, ownsQrSession, qrLoading, setNoticeMessage])

  const submitPasswordLogin = async (event) => {
    event.preventDefault()
    if (passwordLoading) return

    abandonQrLoginIntent()

    const username = passwordForm.username.trim()
    const password = passwordForm.password
    if (!username || !password) {
      setNoticeMessage('error', '请输入账号和密码。')
      return
    }

    setPasswordLoading(true)
    try {
      const resp = await api(`${ZHIHUISHU_API_BASE}/password-login`, {
        method: 'POST',
        body: JSON.stringify({ username, password })
      })

      setZhihuishuLoggedIn(true)
      setLoggedInAccount(username)
      setNoticeMessage('success', pickMessage(resp) || '密码登录成功。')
      await Promise.all([loadCourses(true), loadConfigFromBackend(true), fetchTaskList({ silent: true })])
    } catch (err) {
      setNoticeMessage('error', err.message || '密码登录失败。')
    } finally {
      setPasswordLoading(false)
    }
  }

  const loadZhihuishuStatus = useCallback(async (silent = true) => {
    try {
      const resp = await requestZhihuishuApi('/status', { method: 'GET' })
      const statusPayload = parseObject(resp, 'data')
      const loggedIn = Boolean(statusPayload?.logged_in)
      setZhihuishuLoggedIn(loggedIn)
      if (!loggedIn) setLoggedInAccount('')
      if (!loggedIn) {
        if (!silent) {
          setNoticeMessage('info', '当前未登录智慧树。')
        }
        return statusPayload
      }

      const currentTask = normalizeTaskRecord(statusPayload?.current_task || {})
      if (currentTask) {
        upsertTaskRecord(currentTask)
        selectActiveTask(currentTask.taskId)
      }
      if (statusPayload?.progress && typeof statusPayload.progress === 'object') {
        setProgress(statusPayload.progress)
      }
      if (!silent) {
        setNoticeMessage('success', '状态已同步。')
      }
      return statusPayload
    } catch (err) {
      if (!silent) {
        setNoticeMessage('error', err.message || '状态获取失败。')
      }
      return null
    }
  }, [requestZhihuishuApi, selectActiveTask, setNoticeMessage, upsertTaskRecord])

  const invalidateTaskRequests = useCallback(() => {
    taskSessionGenerationRef.current += 1
    taskRequestsInFlightRef.current.clear()
  }, [])

  const resetZhihuishuSession = useCallback(() => {
    invalidateQrGeneration()
    stopProgressPolling()
    invalidateTaskRequests()
    taskRecordsRef.current = []
    coursesRef.current = []

    setZhihuishuLoggedIn(false)
    setLoggedInAccount('')
    setLoginMethod('qr')

    setQrSessionId('')
    setQrCode('')
    setQrStatus('idle')
    setQrMessage('')
    setQrError('')
    setQrLoading(false)

    setCourseGroups([])
    setCourses([])
    selectCourse('')
    setCourseDetail(null)
    setCourseStructure([])
    setVideos([])
    setProgress(null)
    setTaskRecords([])
    selectActiveTask('')

    setNoticeMessage('info', '已清理智慧树会话状态。')
  }, [invalidateQrGeneration, invalidateTaskRequests, selectActiveTask, selectCourse, setNoticeMessage, stopProgressPolling])

  const logoutZhihuishu = useCallback(async () => {
    invalidateQrGeneration()
    setQrLoading(false)
    invalidateTaskRequests()
    try {
      const resp = await requestZhihuishuApi('/logout', { method: 'POST' })
      resetZhihuishuSession()
      setNoticeMessage('success', pickMessage(resp) || '智慧树会话已退出。')
    } catch (err) {
      setNoticeMessage('error', err.message || '智慧树退出失败。')
    }
  }, [invalidateQrGeneration, invalidateTaskRequests, requestZhihuishuApi, resetZhihuishuSession, setNoticeMessage])

  const logoutSystem = useCallback(async () => {
    if (!window.confirm('确定要退出登录吗？将清除登录状态并返回登录页。')) return
    invalidateQrGeneration()
    setQrLoading(false)
    try {
      await requestZhihuishuApi('/logout', { method: 'POST' })
    } catch (_) {
      // ignore backend logout errors during system logout
    }
    removeToken()
    navigate('/login', { replace: true })
  }, [invalidateQrGeneration, navigate, requestZhihuishuApi])

  useEffect(() => {
    loadSettingsFromStorage()
  }, [loadSettingsFromStorage])

  // Route guard lives in App.jsx (PrivateRoute).
  useEffect(() => {
    if (bootstrapStartedRef.current) return undefined
    bootstrapStartedRef.current = true

    const storedActiveTaskId = readActiveTaskIdFromStorage()
    activeTaskStorageReadyRef.current = true

    void (async () => {
      try {
        const statusPayload = await loadZhihuishuStatus(true)
        if (statusPayload?.logged_in) {
          await Promise.all([
            loadConfigFromBackend(true),
            loadCourses(true),
          ])
          const loadedTasks = await fetchTaskList({
            silent: true,
            preferredTaskId: storedActiveTaskId,
          })

          const normalizedStoredTaskId = parseCourseId(storedActiveTaskId)
          if (normalizedStoredTaskId) {
            const existsInList = loadedTasks.some((task) => task.taskId === normalizedStoredTaskId)
            if (existsInList) {
              selectActiveTask(normalizedStoredTaskId)
            } else {
              beginTaskViewIntent(normalizedStoredTaskId)
              const restoredTask = await fetchTaskDetail(normalizedStoredTaskId, true)
              if (!restoredTask?.taskId) {
                saveActiveTaskIdToStorage('')
                selectActiveTask(loadedTasks[0]?.taskId || '')
              }
            }
          } else if (loadedTasks[0]?.taskId) {
            selectActiveTask(loadedTasks[0].taskId)
          }
        } else {
          selectActiveTask('')
        }
      } finally {
        setBooting(false)
      }
    })()
    return () => {
      stopQrPolling()
      stopProgressPolling()
    }
  }, [
    beginTaskViewIntent,
    fetchTaskDetail,
    fetchTaskList,
    loadConfigFromBackend,
    loadCourses,
    loadZhihuishuStatus,
    readActiveTaskIdFromStorage,
    saveActiveTaskIdToStorage,
    selectActiveTask,
    stopProgressPolling,
    stopQrPolling
  ])

  useEffect(() => {
    if (!activeTaskStorageReadyRef.current) return
    saveActiveTaskIdToStorage(activeTaskId)
  }, [activeTaskId, saveActiveTaskIdToStorage])

  useEffect(() => {
    if (!qrSessionId || qrStatus !== 'pending') return undefined

    const owner = qrSessionOwnerRef.current
    if (owner.sessionId !== qrSessionId) return undefined

    stopQrPolling()
    qrPollRef.current = setInterval(() => {
      void pollQrStatus(qrSessionId, owner.generation)
    }, QR_POLL_INTERVAL_MS)

    return stopQrPolling
  }, [pollQrStatus, qrSessionId, qrStatus, stopQrPolling])

  useEffect(() => {
    fetchTaskDetailRef.current = fetchTaskDetail
  }, [fetchTaskDetail])

  useEffect(() => {
    if (!activeTaskId) {
      stopProgressPolling()
      return undefined
    }

    const pollSeconds = clampPollSeconds(settings.progressPollSeconds)
    stopProgressPolling()

    progressPollRef.current = setInterval(() => {
      void fetchTaskDetailRef.current(activeTaskId, true)
    }, pollSeconds * 1000)

    void fetchTaskDetailRef.current(activeTaskId, true)

    return stopProgressPolling
  }, [activeTaskId, settings.progressPollSeconds, stopProgressPolling])

  useEffect(() => {
    if (!selectedCourseId) {
      setCourseDetail(null)
      setCourseStructure([])
      setVideos([])
      setProgress(null)
      setCourseDetailLoading(false)
      setVideosLoading(false)
      setProgressLoading(false)
      return
    }
    setCourseDetail(null)
    setCourseStructure([])
    setVideos([])
    setProgress(null)
    setVideosLoading(false)
    setProgressLoading(false)
    void loadCourseDetail(selectedCourseId, true)
  }, [loadCourseDetail, selectedCourseId])

  const qrStatusText = useMemo(() => {
    if (qrStatus === 'loading') return '加载中'
    if (qrStatus === 'pending') return '等待扫码'
    if (qrStatus === 'success') return '登录成功'
    if (qrStatus === 'failed') return '登录失败'
    return '未知状态'
  }, [qrStatus])

  const selectedCourse = useMemo(() => {
    if (!selectedCourseId) return null
    if (courseDetail && getZhihuishuCourseId(courseDetail) === selectedCourseId) {
      return {
        ...courses.find((course) => getZhihuishuCourseId(course) === selectedCourseId),
        ...courseDetail
      }
    }
    return courses.find((course) => getZhihuishuCourseId(course) === selectedCourseId) || null
  }, [courseDetail, courses, selectedCourseId])

  const sortedTasks = useMemo(() => {
    return [...taskRecords].sort((a, b) => {
      const aTime = new Date(a.updatedAt || a.startedAt || 0).getTime()
      const bTime = new Date(b.updatedAt || b.startedAt || 0).getTime()
      return bTime - aTime
    })
  }, [taskRecords])

  const selectedCourseProgress = useMemo(() => {
    const payload = parseObject(progress, '')
    return {
      total: Number(payload?.total ?? 0) || 0,
      completed: Number(payload?.completed ?? 0) || 0,
      failed: Number(payload?.failed ?? 0) || 0,
      percentage: clampPercentage(payload?.percentage ?? 0),
      currentVideo: payload?.current_video || payload?.currentTask || '',
      estimatedTime: payload?.estimated_time || payload?.estimatedTime || ''
    }
  }, [progress])

  const activeTaskSummary = useMemo(() => {
    const activeTask = taskRecords.find((task) => task.taskId === activeTaskId) || null
    const payload = parseObject(activeTask?.progress, '')
    return {
      courseName: activeTask?.courseName || '',
      status: activeTask?.status || payload?.status || '暂无',
      message: activeTask?.message || payload?.message || '暂无',
      currentVideo: activeTask?.currentTask || payload?.current_video || payload?.currentTask || '',
      total: Number(payload?.total ?? activeTask?.total ?? 0) || 0,
      completed: Number(payload?.completed ?? activeTask?.completed ?? 0) || 0,
      failed: Number(payload?.failed ?? activeTask?.failed ?? 0) || 0,
      percentage: clampPercentage(payload?.percentage ?? activeTask?.percentage ?? 0),
      estimatedTime: payload?.estimated_time || payload?.estimatedTime || ''
    }
  }, [activeTaskId, taskRecords])

  const courseLabel = selectedCourse?.courseName || selectedCourse?.name || selectedCourse?.title || selectedCourseId

  if (booting) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="智慧树" title="课程学习" />
        <p role="status" className="flex items-center gap-2 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />
          正在检查登录状态...
        </p>
      </div>
    )
  }

  return (
    <div className="min-w-0 space-y-6">
      <PageHeader
        eyebrow="智慧树"
        title="课程学习"
        actions={(
          <AccountChip
            ready={zhihuishuLoggedIn}
            account={loggedInAccount}
            onClick={() => setActiveTab('account')}
          />
        )}
      >
        <WorkspaceTabs id="zhs" label="智慧树工作区" tabs={ZHIHUISHU_TABS} activeTab={activeTab} onChange={setActiveTab} />
      </PageHeader>

      {activeTab === 'courses' && (
        <section
          id="zhs-panel-courses"
          role="tabpanel"
          aria-labelledby="zhs-tab-courses"
          tabIndex="0"
          className={courses.length > 0 ? 'grid grid-cols-1 items-start gap-6 lg:grid-cols-2' : 'max-w-2xl'}
        >
          <div className={`${CARD_CLASS} space-y-4`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-text">选择课程</h2>
              <button
                type="button"
                className={GHOST_BUTTON_CLASS}
                onClick={() => {
                  void loadCourses(false)
                }}
                disabled={coursesLoading}
              >
                <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                {coursesLoading ? '刷新中...' : '刷新课程'}
              </button>
            </div>

            {courses.length > 0 ? (
              <>
                <div>
                  <label htmlFor="zhs-course" className={LABEL_CLASS}>分组课程</label>
                  <select
                    id="zhs-course"
                    className={`${FIELD_CLASS} cursor-pointer`}
                    value={selectedCourseId}
                    onChange={(event) => {
                      selectCourse(event.target.value)
                    }}
                  >
                    <option value="">请选择课程</option>
                    {courseGroups.map((group) => (
                      <optgroup key={group.group} label={`${group.group}（${group.courses.length}）`}>
                        {group.courses.map((course) => {
                          const id = getZhihuishuCourseId(course)
                          const title = course.courseName || course.name || course.title || id
                          return <option key={`${group.group}-${id}`} value={id}>{title}</option>
                        })}
                      </optgroup>
                    ))}
                  </select>
                </div>
                <button
                  type="button"
                  className={`${PRIMARY_BUTTON_CLASS} w-full`}
                  onClick={() => setActiveTab('study')}
                  disabled={!selectedCourseId}
                >
                  下一步：学习配置
                </button>
              </>
            ) : !coursesLoading && (
              <div role="status" className="space-y-3 text-sm text-text-muted">
                <p>{zhihuishuLoggedIn ? '没有读到课程，可稍后刷新重试。' : '登录智慧树后即可看到课程。'}</p>
                {!zhihuishuLoggedIn && (
                  <button type="button" className={PRIMARY_BUTTON_CLASS} onClick={() => setActiveTab('account')}>
                    前往登录
                  </button>
                )}
              </div>
            )}
          </div>

          {courses.length > 0 && (
            <div className={`${CARD_CLASS} space-y-4`}>
              {!selectedCourseId ? (
                <p className="text-sm text-text-muted">请选择课程查看详情与进度。</p>
              ) : (
                <>
                  <div className="min-w-0">
                    <h2 className="break-words text-lg font-semibold text-text">{courseLabel}</h2>
                    <p className="mt-1 break-all text-xs text-text-muted">
                      {selectedCourse?._groupName || selectedCourse?.semesterName || selectedCourse?.termName || '未分类'} · ID {selectedCourseId}
                    </p>
                    {courseDetailLoading && <p className="mt-2 text-xs text-text-muted">正在加载课程详情...</p>}
                  </div>

                  <div className={`${PANEL_CLASS} space-y-3`}>
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <h3 className="text-sm font-semibold text-text">学习进度</h3>
                      <button
                        type="button"
                        className={SECONDARY_BUTTON_CLASS}
                        onClick={() => {
                          const courseTask = taskRecords.find((task) => task.taskId === activeTaskId && task.courseId === selectedCourseId)
                          if (courseTask) {
                            void fetchTaskDetail(courseTask.taskId, false)
                          } else {
                            void loadCourseProgress(selectedCourseId, false)
                          }
                        }}
                        disabled={progressLoading}
                      >
                        {progressLoading ? '刷新中...' : '刷新进度'}
                      </button>
                    </div>
                    {progress ? (
                      <>
                        <div
                          className="h-2 overflow-hidden rounded-full bg-border/60"
                          role="progressbar"
                          aria-valuenow={Math.round(selectedCourseProgress.percentage)}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-label="课程学习进度"
                        >
                          <div className="h-full rounded-full bg-primary transition-all duration-200" style={{ width: `${selectedCourseProgress.percentage}%` }} />
                        </div>
                        <p className="text-xs text-text-muted">
                          {progress.status ? `${progress.status} · ` : ''}
                          {selectedCourseProgress.completed}/{selectedCourseProgress.total}（{Math.round(selectedCourseProgress.percentage)}%）
                          {selectedCourseProgress.failed > 0 ? ` · 失败 ${selectedCourseProgress.failed}` : ''}
                          {selectedCourseProgress.estimatedTime ? ` · 预计剩余 ${selectedCourseProgress.estimatedTime}` : ''}
                        </p>
                        <p className="break-words text-sm text-text">消息：{progress.message || '暂无'}</p>
                        {selectedCourseProgress.currentVideo && (
                          <p className="break-words text-sm text-text-muted">当前视频：{selectedCourseProgress.currentVideo}</p>
                        )}
                      </>
                    ) : (
                      <p className="text-sm text-text-muted">暂无进度。</p>
                    )}
                  </div>

                  <div className={`${PANEL_CLASS} space-y-3`}>
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <h3 className="text-sm font-semibold text-text">课程内容</h3>
                      <button
                        type="button"
                        className={SECONDARY_BUTTON_CLASS}
                        onClick={() => {
                          void loadVideos(selectedCourseId)
                        }}
                        disabled={videosLoading}
                      >
                        {videosLoading ? '加载中...' : '查看视频列表/结构'}
                      </button>
                    </div>
                    {courseStructure.length === 0 && videos.length === 0 && (
                      <p className="text-sm text-text-muted">尚未加载课程内容。</p>
                    )}
                    {courseStructure.length > 0 && (
                      <ul className="max-h-48 space-y-2 overflow-y-auto pr-1 text-sm">
                        {courseStructure.map((section, index) => (
                          <li key={`${section.id || index}`} className="flex items-start justify-between gap-3 rounded-lg bg-surface px-3 py-2">
                            <p className="min-w-0 break-words font-medium text-text">{section.title || `结构 ${index + 1}`}</p>
                            <span className="shrink-0 text-xs text-text-muted">{Array.isArray(section.videos) ? section.videos.length : 0} 个视频</span>
                          </li>
                        ))}
                      </ul>
                    )}
                    {videos.length > 0 && (
                      <details>
                        <summary className="cursor-pointer text-sm font-medium text-text">视频（{videos.length}）</summary>
                        <ul className="mt-2 max-h-56 space-y-2 overflow-y-auto pr-1 text-sm">
                          {videos.map((video, index) => {
                            const title = video.name || video.title || video.videoName || `视频 ${index + 1}`
                            return (
                              <li key={`${title}-${index}`} className="rounded-lg bg-surface px-3 py-2">
                                <div className="flex items-start justify-between gap-3">
                                  <span className="min-w-0 break-words text-text">{title}</span>
                                  <span className="shrink-0 text-xs text-text-muted">{video.status || 'unknown'}</span>
                                </div>
                                {video.sectionTitle && <p className="mt-0.5 text-xs text-text-muted">章节：{video.sectionTitle}</p>}
                              </li>
                            )
                          })}
                        </ul>
                      </details>
                    )}
                  </div>
                </>
              )}
            </div>
          )}
        </section>
      )}

      {activeTab === 'study' && (
        <section id="zhs-panel-study" role="tabpanel" aria-labelledby="zhs-tab-study" tabIndex="0" className="max-w-3xl space-y-4">
          <div className={`${CARD_CLASS} space-y-5`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-medium text-text-muted">当前课程</p>
                <h2 className="mt-1 break-words text-lg font-semibold text-text">{selectedCourseId ? courseLabel : '尚未选择课程'}</h2>
              </div>
              <button
                type="button"
                className={selectedCourseId ? GHOST_BUTTON_CLASS : PRIMARY_BUTTON_CLASS}
                onClick={() => setActiveTab('courses')}
              >
                {selectedCourseId ? '换课程' : '去选择课程'}
              </button>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="zhs-speed" className={LABEL_CLASS}>学习倍速</label>
                <select
                  id="zhs-speed"
                  className={`${FIELD_CLASS} cursor-pointer`}
                  value={settings.speed}
                  onChange={(event) => setSettings((prev) => ({ ...prev, speed: event.target.value }))}
                >
                  {SPEED_OPTIONS.map((speed) => <option key={speed} value={speed}>{speed}x</option>)}
                </select>
              </div>
              <div className="flex min-h-[44px] items-center justify-between gap-3 self-end rounded-xl border border-border pl-4 pr-1">
                <span className="text-sm font-semibold text-text">
                  自动答题<span className="ml-1 text-xs font-normal text-text-muted">视频弹题</span>
                </span>
                <Toggle
                  label="自动答题"
                  checked={settings.autoAnswer}
                  onChange={(next) => setSettings((prev) => ({ ...prev, autoAnswer: next }))}
                />
              </div>
            </div>

            {selectedCourseId && (
              <>
                <div>
                  <label htmlFor="zhs-end-chapter" className={LABEL_CLASS}>学到哪一章</label>
                  <div className="flex gap-2">
                    <select
                      id="zhs-end-chapter"
                      className={`${FIELD_CLASS} cursor-pointer`}
                      value={chapterScope.endChapterId}
                      disabled={chapterScope.chapters.length === 0}
                      aria-describedby="zhs-end-chapter-hint"
                      onChange={(event) => setEndChapter(event.target.value)}
                    >
                      <option value="">全部章节</option>
                      {chapterScope.chapters.map((chapter, index) => (
                        <option key={chapter.id} value={chapter.id}>
                          {index + 1}. {chapter.title}（{chapter.videoCount} 个视频）
                        </option>
                      ))}
                    </select>
                    {chapterScope.chapters.length === 0 && (
                      <button
                        type="button"
                        className={`${SECONDARY_BUTTON_CLASS} shrink-0`}
                        onClick={() => {
                          void loadChapters(selectedCourseId)
                        }}
                        disabled={chaptersLoading}
                      >
                        {chaptersLoading ? '章节加载中...' : '加载章节'}
                      </button>
                    )}
                  </div>
                  <p id="zhs-end-chapter-hint" className="mt-1.5 text-xs text-text-muted">{chapterScope.hint}</p>
                </div>

                <div className="flex flex-col gap-2 sm:flex-row">
                  <button
                    type="button"
                    className={PRIMARY_BUTTON_CLASS}
                    onClick={() => {
                      void startCourseTask('course')
                    }}
                    disabled={startLoadingType !== ''}
                  >
                    <Play className="h-4 w-4" aria-hidden="true" />
                    {startLoadingType === 'course' ? '启动中...' : '启动课程任务'}
                  </button>
                  <button
                    type="button"
                    className={SECONDARY_BUTTON_CLASS}
                    onClick={() => {
                      void startCourseTask('ai-course')
                    }}
                    disabled={startLoadingType !== ''}
                  >
                    <Play className="h-4 w-4" aria-hidden="true" />
                    {startLoadingType === 'ai-course' ? '启动中...' : '启动 AI 任务'}
                  </button>
                </div>
              </>
            )}
          </div>

          <details
            className={CARD_CLASS}
            open={defaultsOpen}
            onToggle={(event) => setDefaultsOpen(event.currentTarget.open)}
          >
            <summary className="flex min-h-[28px] cursor-pointer list-none items-center justify-between gap-3 font-semibold text-text [&::-webkit-details-marker]:hidden">
              默认设置
              <ChevronDown className={`h-4 w-4 text-text-muted transition-transform ${defaultsOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
            </summary>
            <div className="mt-4 space-y-4">
              <p className="text-sm text-text-muted">保存后，上面的倍速、自动答题和这里的轮询间隔会在下次打开时沿用。</p>
              <div className="sm:max-w-xs">
                <label htmlFor="zhs-poll" className={LABEL_CLASS}>进度轮询间隔（秒）</label>
                <input
                  id="zhs-poll"
                  type="number"
                  min={String(MIN_PROGRESS_POLL_SECONDS)}
                  max={String(MAX_PROGRESS_POLL_SECONDS)}
                  value={settings.progressPollSeconds}
                  onChange={(event) => setSettings((prev) => ({ ...prev, progressPollSeconds: clampPollSeconds(event.target.value) }))}
                  className={FIELD_CLASS}
                />
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className={SECONDARY_BUTTON_CLASS}
                  onClick={() => {
                    void saveSettings(settings)
                  }}
                  disabled={settingsSaving}
                >
                  {settingsSaving ? '保存中...' : '保存为默认'}
                </button>
                <button
                  type="button"
                  className={GHOST_BUTTON_CLASS}
                  onClick={() => {
                    void loadConfigFromBackend(false)
                  }}
                  disabled={settingsSaving}
                >
                  同步配置
                </button>
              </div>
            </div>
          </details>
        </section>
      )}

      {activeTab === 'tasks' && (
        <section id="zhs-panel-tasks" role="tabpanel" aria-labelledby="zhs-tab-tasks" tabIndex="0" className="space-y-4">
          <div className={`${CARD_CLASS} space-y-4`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-text">当前任务</h2>
              <button type="button" className={GHOST_BUTTON_CLASS} onClick={refreshTaskList} disabled={progressLoading}>
                <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                刷新列表
              </button>
            </div>

            {activeTaskId ? (
              <>
                <div className="min-w-0">
                  <p className="break-words font-semibold text-text">{activeTaskSummary.courseName || '智慧树任务'}</p>
                  <p className="mt-1 break-all text-xs text-text-muted">任务 ID：{activeTaskId}</p>
                </div>
                <div className="space-y-2">
                  <div
                    className="h-2 overflow-hidden rounded-full bg-border/60"
                    role="progressbar"
                    aria-valuenow={Math.round(activeTaskSummary.percentage)}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label="最近任务进度"
                  >
                    <div className="h-full rounded-full bg-primary transition-all duration-200" style={{ width: `${activeTaskSummary.percentage}%` }} />
                  </div>
                  <p className="text-xs text-text-muted">
                    {activeTaskSummary.completed}/{activeTaskSummary.total}（{Math.round(activeTaskSummary.percentage)}%）
                    {activeTaskSummary.failed > 0 ? ` · 失败 ${activeTaskSummary.failed}` : ''}
                    {activeTaskSummary.estimatedTime ? ` · 预计剩余 ${activeTaskSummary.estimatedTime}` : ''}
                  </p>
                </div>
                <div className="space-y-1 text-sm">
                  <p className="text-text">状态：{activeTaskSummary.status}</p>
                  <p className="break-words text-text-muted">消息：{activeTaskSummary.message}</p>
                  {activeTaskSummary.currentVideo && (
                    <p className="break-words text-text-muted">当前视频：{activeTaskSummary.currentVideo}</p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={SECONDARY_BUTTON_CLASS} onClick={pauseTask} disabled={taskActionLoading !== ''}>
                    <Pause className="h-4 w-4" aria-hidden="true" />
                    {taskActionLoading === 'pause' ? '暂停中...' : '暂停'}
                  </button>
                  <button type="button" className={SECONDARY_BUTTON_CLASS} onClick={resumeTask} disabled={taskActionLoading !== ''}>
                    <Play className="h-4 w-4" aria-hidden="true" />
                    {taskActionLoading === 'resume' ? '恢复中...' : '恢复'}
                  </button>
                  <button type="button" className={DANGER_BUTTON_CLASS} onClick={cancelTask} disabled={taskActionLoading !== ''}>
                    <X className="h-4 w-4" aria-hidden="true" />
                    {taskActionLoading === 'cancel' ? '取消中...' : '取消'}
                  </button>
                </div>
              </>
            ) : sortedTasks.length > 0 ? (
              <p role="status" className="text-sm text-text-muted">在下方任务记录中点「查看详情」查看进度。</p>
            ) : (
              <div role="status" className="space-y-3 text-sm text-text-muted">
                <p>还没有任务。</p>
                <button
                  type="button"
                  className={PRIMARY_BUTTON_CLASS}
                  onClick={() => setActiveTab(zhihuishuLoggedIn ? 'study' : 'account')}
                >
                  {zhihuishuLoggedIn ? '去学习配置' : '前往登录'}
                </button>
              </div>
            )}
          </div>

          {sortedTasks.length > 0 && (
            <div className={`${CARD_CLASS} space-y-3`}>
              <h2 className="text-lg font-semibold text-text">任务记录</h2>
              <ul className="space-y-3">
                {sortedTasks.map((task) => (
                  <li key={task.taskId} className={`${PANEL_CLASS} space-y-2`}>
                    <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
                      <div className="min-w-0">
                        <p className="break-words font-semibold text-text">{task.courseName || '智慧树任务'}</p>
                        <p className="mt-1 break-all text-xs text-text-muted">任务 ID：{task.taskId}{task.taskId === activeTaskId ? ' · 当前查看' : ''}</p>
                      </div>
                      <p className="shrink-0 text-sm text-text">状态：{task.status || 'unknown'}</p>
                    </div>
                    <p className="break-words text-sm text-text-muted">
                      进度：{task.completed || 0}/{task.total || 0}（{Math.round(Number(task.percentage || 0))}%）{task.currentTask ? ` · ${task.currentTask}` : ''}
                    </p>
                    {task.message && <p className="break-words text-sm text-text-muted">消息：{task.message}</p>}
                    <p className="text-xs text-text-muted">
                      {task.taskType === 'ai-course' ? 'AI 任务' : '课程任务'} · 更新于 {new Date(task.updatedAt || task.startedAt).toLocaleString()}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        className={SECONDARY_BUTTON_CLASS}
                        onClick={() => {
                          void fetchTaskDetail(task.taskId, false)
                        }}
                        disabled={taskActionLoading !== '' || taskItemActionLoading === task.taskId}
                      >
                        查看详情
                      </button>
                      {!TERMINAL_ZHIHUISHU_TASK_STATUSES.has(task.status) && (
                        <button
                          type="button"
                          className={`${GHOST_BUTTON_CLASS} hover:text-danger`}
                          onClick={() => {
                            void cancelTaskById(task.taskId)
                          }}
                          disabled={taskActionLoading !== '' || taskItemActionLoading === task.taskId}
                        >
                          {taskItemActionLoading === task.taskId ? '取消中...' : '取消该任务'}
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {activeTab === 'account' && (
        <section id="zhs-panel-account" role="tabpanel" aria-labelledby="zhs-tab-account" tabIndex="0" className="max-w-2xl">
          {zhihuishuLoggedIn ? (
            <div className={`${CARD_CLASS} space-y-4`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-lg font-semibold text-text">智慧树已登录</h2>
                  {loggedInAccount && <p className="mt-1 break-all text-sm text-text-muted">账号：{loggedInAccount}</p>}
                </div>
                <button
                  type="button"
                  className={GHOST_BUTTON_CLASS}
                  onClick={() => {
                    void loadZhihuishuStatus(false)
                  }}
                >
                  <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                  同步状态
                </button>
              </div>
              <div className={`${PANEL_CLASS} grid grid-cols-1 gap-2 text-sm sm:grid-cols-2`}>
                <p className="break-all text-text">当前任务：{activeTaskSummary.courseName || activeTaskId || '无'}</p>
                <p className="text-text">任务记录：{taskRecords.length} 条</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" className={DANGER_BUTTON_CLASS} onClick={logoutZhihuishu}>退出智慧树会话</button>
                <button type="button" className={GHOST_BUTTON_CLASS} onClick={resetZhihuishuSession}>清理智慧树会话状态</button>
                {!isLocal && (
                  <button type="button" className={GHOST_BUTTON_CLASS} onClick={() => { void logoutSystem() }}>系统退出登录</button>
                )}
              </div>
              <p className="text-xs text-text-muted">退出会结束智慧树会话并取消相关任务；清理只重置本页状态。</p>
            </div>
          ) : (
            <div className={`${CARD_CLASS} space-y-5`}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-lg font-semibold text-text">登录智慧树</h2>
                {/* Only the chosen method's form shows, so the two never compete on screen. */}
                <div role="radiogroup" aria-label="登录方式" className="inline-flex rounded-xl bg-surface-hover p-1">
                  {[
                    { value: 'qr', label: '二维码登录' },
                    { value: 'password', label: '账号密码登录' },
                  ].map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      role="radio"
                      aria-checked={loginMethod === opt.value}
                      onClick={() => {
                        if (opt.value === 'password') abandonQrLoginIntent()
                        setLoginMethod(opt.value)
                      }}
                      className={`min-h-[40px] rounded-lg px-3 text-sm font-medium transition-colors ${
                        loginMethod === opt.value
                          ? 'bg-surface text-text shadow-sm'
                          : 'text-text-muted hover:text-text'
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {loginMethod === 'qr' ? (
                <div className="flex flex-col items-center gap-5 sm:flex-row">
                  <div className="flex h-48 w-48 shrink-0 items-center justify-center overflow-hidden rounded-2xl border border-dashed border-border bg-surface-hover/40">
                    {qrLoading ? (
                      <Loader2 className="h-8 w-8 animate-spin text-primary" aria-hidden="true" />
                    ) : qrCode ? (
                      <img src={`data:image/png;base64,${qrCode}`} alt="智慧树二维码" className="h-full w-full bg-white object-contain" />
                    ) : (
                      <QrCode className="h-12 w-12 text-text-muted" aria-hidden="true" />
                    )}
                  </div>
                  <div className="w-full min-w-0 space-y-4 text-center sm:text-left">
                    {qrError ? (
                      <p role="alert" className="break-words text-sm text-danger">{qrError}</p>
                    ) : (
                      <p className="break-words text-sm text-text-muted">
                        {qrStatus === 'idle' ? '用智慧树 App 扫码登录。' : (qrMessage || qrStatusText)}
                      </p>
                    )}
                    <button
                      type="button"
                      className={PRIMARY_BUTTON_CLASS}
                      onClick={() => {
                        void startQrLogin()
                      }}
                      disabled={qrLoading}
                    >
                      {qrLoading ? '生成中...' : '生成二维码'}
                    </button>
                  </div>
                </div>
              ) : (
                <form className="space-y-4" onSubmit={submitPasswordLogin}>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <Input id="zhs-username" label="智慧树账号" type="text" autoComplete="username" value={passwordForm.username} onChange={(event) => setPasswordForm((prev) => ({ ...prev, username: event.target.value }))} required />
                    <Input id="zhs-password" label="密码" type="password" autoComplete="current-password" value={passwordForm.password} onChange={(event) => setPasswordForm((prev) => ({ ...prev, password: event.target.value }))} required />
                  </div>
                  <button type="submit" className={`${PRIMARY_BUTTON_CLASS} w-full sm:w-auto`} disabled={passwordLoading}>
                    {passwordLoading ? '登录中...' : '密码登录'}
                  </button>
                </form>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
