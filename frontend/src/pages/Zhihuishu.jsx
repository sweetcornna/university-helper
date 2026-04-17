import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  List,
  Loader2,
  Pause,
  Play,
  QrCode,
  RefreshCcw,
  X
} from 'lucide-react'
import { Input } from '../components'
import { api } from '../utils/api'
import { isAuthenticated, removeToken } from '../utils/auth'
import { applyCourseProgressToTaskRecords } from '../utils/zhihuishuTasks'

const QR_POLL_INTERVAL_MS = 2000
const DEFAULT_PROGRESS_POLL_SECONDS = 5
const MIN_PROGRESS_POLL_SECONDS = 2
const MAX_PROGRESS_POLL_SECONDS = 60
const SETTINGS_STORAGE_KEY = 'zhihuishu_page_settings_v1'
const ACTIVE_TASK_ID_STORAGE_KEY = 'zhihuishu_active_task_id_v1'
const ZHIHUISHU_API_BASE = '/course/zhihuishu'

const GLASS_CARD_CLASS =
  'rounded-2xl border border-white/20 bg-white/80 p-6 shadow-lg backdrop-blur-lg transition-all duration-200'
const PANEL_CLASS =
  'rounded-xl border border-white/30 bg-white/60 p-4 backdrop-blur-sm transition-all duration-200'
const TAB_BUTTON_CLASS =
  'min-h-[44px] min-w-[44px] rounded-xl px-4 py-2 font-medium cursor-pointer transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-primary/30'
const FIELD_CLASS =
  'w-full min-h-[44px] rounded-xl border border-white/30 bg-white/70 px-4 py-2 text-text transition-all duration-200 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20'
const ACTION_BUTTON_CLASS =
  'min-h-[44px] min-w-[44px] rounded-xl px-4 py-2 font-medium text-white cursor-pointer transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:cursor-not-allowed disabled:opacity-60'

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

const parseTaskIdsInput = (value) => {
  if (!value) return []
  const seen = new Set()
  return value
    .split(/[\s,，;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item) => {
      if (seen.has(item)) return false
      seen.add(item)
      return true
    })
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
    courseId: parseCourseId(payload?.course_id || payload?.courseId || fallback.courseId),
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
  const progressPollRef = useRef(null)
  const activeTaskStorageReadyRef = useRef(false)

  const [booting, setBooting] = useState(true)
  const [activeTab, setActiveTab] = useState('login')
  const [notice, setNotice] = useState({ type: 'info', message: '' })

  const [loginMethod, setLoginMethod] = useState('qr')
  const [zhihuishuLoggedIn, setZhihuishuLoggedIn] = useState(false)

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

  const [progress, setProgress] = useState(null)
  const [progressLoading, setProgressLoading] = useState(false)

  const [startLoadingType, setStartLoadingType] = useState('')
  const [taskActionLoading, setTaskActionLoading] = useState('')
  const [taskItemActionLoading, setTaskItemActionLoading] = useState('')
  const [taskRecords, setTaskRecords] = useState([])
  const [activeTaskId, setActiveTaskId] = useState('')
  const [taskIdsInput, setTaskIdsInput] = useState('')
  const [settingsSaving, setSettingsSaving] = useState(false)

  const [settings, setSettings] = useState({
    speed: '1.0',
    autoAnswer: true,
    progressPollSeconds: DEFAULT_PROGRESS_POLL_SECONDS
  })

  const setNoticeMessage = useCallback((type, message) => {
    if (!message) return
    setNotice({ type, message })
  }, [])

  const stopQrPolling = useCallback(() => {
    if (qrPollRef.current) {
      clearInterval(qrPollRef.current)
      qrPollRef.current = null
    }
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

  const upsertTaskRecord = useCallback((nextTask) => {
    if (!nextTask?.taskId) return
    setTaskRecords((prev) => {
      const index = prev.findIndex((task) => task.taskId === nextTask.taskId)
      if (index === -1) {
        return [nextTask, ...prev].slice(0, 20)
      }
      const copy = [...prev]
      copy[index] = { ...copy[index], ...nextTask }
      return copy
    })
  }, [])

  const mergeTaskRecords = useCallback((nextTasks, replaceAll = false) => {
    setTaskRecords((prev) => {
      const base = replaceAll ? [] : prev
      const map = new Map(base.map((task) => [task.taskId, task]))
      nextTasks.forEach((task) => {
        if (!task?.taskId) return
        map.set(task.taskId, { ...(map.get(task.taskId) || {}), ...task })
      })
      return Array.from(map.values()).slice(0, 50)
    })
  }, [])

  const loadSettingsFromStorage = useCallback(() => {
    try {
      const raw = localStorage.getItem(SETTINGS_STORAGE_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw)
      setSettings((prev) => ({
        ...prev,
        speed: String(parsed.speed || prev.speed),
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

  const loadConfigFromBackend = useCallback(async (silent = true) => {
    try {
      const resp = await requestZhihuishuApi('/config', { method: 'GET' })
      const config = parseObject(resp, 'data', 'config')
      setSettings((prev) => {
        const merged = {
          ...prev,
          speed: String(config?.speed ?? prev.speed),
          autoAnswer: typeof config?.auto_answer === 'boolean'
            ? config.auto_answer
            : (typeof config?.autoAnswer === 'boolean' ? config.autoAnswer : prev.autoAnswer)
        }
        saveSettingsToStorage(merged)
        return merged
      })
      if (!silent) {
        setNoticeMessage('success', pickMessage(resp) || '已同步后端配置。')
      }
      return true
    } catch (err) {
      if (!silent) {
        setNoticeMessage('info', '后端配置不可用，已使用本地配置。')
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
      setNoticeMessage('success', pickMessage(resp) || '配置已保存到后端和本地。')
    } catch (err) {
      if (savedToStorage) {
        setNoticeMessage('info', '后端配置保存失败，已保存到本地。')
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
    setCourses(flatCourses)
    setSelectedCourseId((prev) => {
      if (prev && flatCourses.some((course) => parseCourseId(course?.courseId || course?.id) === prev)) {
        return prev
      }
      return parseCourseId(flatCourses[0]?.courseId || flatCourses[0]?.id)
    })
    return flatCourses
  }, [])

  const loadCourseDetail = useCallback(async (courseId, silent = false) => {
    if (!courseId) return null

    setCourseDetailLoading(true)
    try {
      const resp = await requestZhihuishuApi(`/courses/${courseId}`, { method: 'GET' })
      const detail = parseObject(resp, 'data')
      setCourseDetail(detail)

      const structure = extractCourseStructure(detail)
      setCourseStructure(structure)

      const detailVideos = flattenStructureVideos(structure)
      if (detailVideos.length > 0) {
        setVideos(detailVideos)
      }

      if (!silent) {
        setNoticeMessage('success', pickMessage(resp) || '课程详情已更新。')
      }
      return detail
    } catch (err) {
      const fallback = courses.find((course) => parseCourseId(course?.courseId || course?.id) === courseId) || null
      setCourseDetail(fallback)
      setCourseStructure([])
      if (!silent) {
        setNoticeMessage('info', '课程详情接口不可用，已使用课程列表数据。')
      }
      return fallback
    } finally {
      setCourseDetailLoading(false)
    }
  }, [courses, requestZhihuishuApi, setNoticeMessage])

  const loadVideos = useCallback(async (courseId) => {
    if (!courseId) {
      setNoticeMessage('error', '请先选择课程。')
      return
    }

    setVideosLoading(true)
    try {
      const detail = await loadCourseDetail(courseId, true)
      const structure = extractCourseStructure(detail || {})
      const detailVideos = flattenStructureVideos(structure)

      if (detailVideos.length > 0) {
        setCourseStructure(structure)
        setVideos(detailVideos)
        setNoticeMessage('success', `已从课程结构加载 ${detailVideos.length} 个视频。`)
        return
      }

      const legacyResp = await api(`${ZHIHUISHU_API_BASE}/videos/${courseId}`, { method: 'GET' })
      const legacyVideos = parseList(legacyResp, 'data', 'videos')
      setVideos(legacyVideos)
      if (courseStructure.length === 0 && legacyVideos.length > 0) {
        setCourseStructure([
          {
            id: `${courseId}-legacy`,
            title: '视频任务',
            videos: legacyVideos
          }
        ])
      }
      setNoticeMessage('success', `已加载 ${legacyVideos.length} 个视频任务。`)
    } catch (err) {
      setNoticeMessage('error', err.message || '加载视频列表失败。')
    } finally {
      setVideosLoading(false)
    }
  }, [courseStructure.length, loadCourseDetail, setNoticeMessage])

  const loadCourses = useCallback(async (silent = false) => {
    setCoursesLoading(true)
    try {
      let groups = []
      try {
        const groupedResp = await requestZhihuishuApi('/courses/grouped', { method: 'GET' })
        groups = normalizeCourseGroups(groupedResp)
      } catch (_) {
        const legacyResp = await api(`${ZHIHUISHU_API_BASE}/courses`, { method: 'GET' })
        groups = normalizeCourseGroups(legacyResp)
      }

      const flatCourses = applyGroupedCourses(groups)
      setZhihuishuLoggedIn(true)
      if (!silent) {
        setNoticeMessage(
          'success',
          flatCourses.length > 0 ? '分组课程加载完成。' : '暂无课程数据。'
        )
      }
      return flatCourses
    } catch (err) {
      if (!silent) {
        setNoticeMessage('error', err.message || '加载课程失败。')
      }
      return []
    } finally {
      setCoursesLoading(false)
    }
  }, [applyGroupedCourses, requestZhihuishuApi, setNoticeMessage])

  const loadCourseProgress = useCallback(async (courseId, silent = true) => {
    if (!courseId) return null

    setProgressLoading(true)
    try {
      const resp = await api(`${ZHIHUISHU_API_BASE}/progress/${courseId}`, { method: 'GET' })
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

      setProgress(normalizedProgress)
      setTaskRecords((prev) =>
        applyCourseProgressToTaskRecords(prev, {
          courseId,
          activeTaskId,
          progress: normalizedProgress,
          updatedAt: new Date().toISOString()
        })
      )
      if (!silent) {
        setNoticeMessage('success', '课程进度已刷新。')
      }
      return progressPayload
    } catch (err) {
      if (!silent) {
        setNoticeMessage('error', err.message || '查询进度失败。')
      }
      return null
    } finally {
      setProgressLoading(false)
    }
  }, [activeTaskId, setNoticeMessage])

  const fetchTaskDetail = useCallback(async (taskId, silent = false) => {
    if (!taskId) return null

    try {
      const resp = await requestZhihuishuApi(`/tasks/${taskId}`, { method: 'GET' })
      const detail = parseObject(resp, 'data')
      const previous = taskRecords.find((task) => task.taskId === taskId) || {}
      const normalized = normalizeTaskRecord(detail, previous)
      if (!normalized) return null

      const fallbackCourse = courses.find((course) => parseCourseId(course?.courseId || course?.id) === normalized.courseId)
      if (!normalized.courseName && fallbackCourse) {
        normalized.courseName = fallbackCourse.courseName || fallbackCourse.name || fallbackCourse.title || normalized.courseId
      }

      upsertTaskRecord(normalized)
      setActiveTaskId(normalized.taskId)
      if (normalized.courseId === selectedCourseId) {
        setProgress({
          status: normalized.status,
          message: normalized.message,
          current_video: normalized.currentTask,
          total: normalized.total,
          completed: normalized.completed,
          failed: normalized.failed,
          percentage: normalized.percentage
        })
      }
      if (Array.isArray(normalized.videos) && normalized.videos.length > 0 && normalized.courseId === selectedCourseId) {
        setVideos(normalized.videos.map((video, index) => ({
          id: parseCourseId(video?.id || video?.videoId || index + 1),
          title: video?.title || video?.name || video?.videoName || `视频 ${index + 1}`,
          status: video?.status || 'pending'
        })))
      }
      if (!silent) {
        setNoticeMessage('success', pickMessage(resp) || '任务详情已刷新。')
      }
      return normalized
    } catch (err) {
      const fallback = taskRecords.find((task) => task.taskId === taskId)
      if (fallback?.courseId) {
        await loadCourseProgress(fallback.courseId, true)
      }
      if (!silent) {
        setNoticeMessage('error', err.message || '获取任务详情失败。')
      }
      return null
    }
  }, [courses, loadCourseProgress, requestZhihuishuApi, selectedCourseId, setNoticeMessage, taskRecords, upsertTaskRecord])

  const fetchTaskList = useCallback(async ({ silent = false, taskType, courseId, preferredTaskId } = {}) => {
    try {
      const query = buildQuery({
        task_type: taskType,
        course_id: courseId
      })
      const resp = await requestZhihuishuApi(`/tasks${query}`, { method: 'GET' })
      const tasks = parseList(resp, 'data', 'tasks')
      const normalized = tasks
        .map((task) => {
          const item = normalizeTaskRecord(task)
          if (!item) return null
          const linkedCourse = courses.find((course) => parseCourseId(course?.courseId || course?.id) === item.courseId)
          if (!item.courseName && linkedCourse) {
            item.courseName = linkedCourse.courseName || linkedCourse.name || linkedCourse.title || item.courseId
          }
          return item
        })
        .filter(Boolean)

      mergeTaskRecords(normalized, true)
      const preferredId = parseCourseId(preferredTaskId)
      if (preferredId && normalized.some((task) => task.taskId === preferredId)) {
        setActiveTaskId(preferredId)
      } else if (!activeTaskId && normalized[0]?.taskId) {
        setActiveTaskId(normalized[0].taskId)
      }
      if (!silent) {
        setNoticeMessage('success', normalized.length > 0 ? '任务列表已刷新。' : '暂无任务记录。')
      }
      return normalized
    } catch (err) {
      if (!silent) {
        setNoticeMessage('error', err.message || '加载任务列表失败。')
      }
      return []
    }
  }, [activeTaskId, courses, mergeTaskRecords, requestZhihuishuApi, setNoticeMessage])

  const refreshTaskList = useCallback(async () => {
    const ids = parseTaskIdsInput(taskIdsInput)
    if (ids.length > 0) {
      const details = await Promise.all(ids.map((taskId) => fetchTaskDetail(taskId, true)))
      const successCount = details.filter(Boolean).length
      if (successCount === 0) {
        setNoticeMessage('info', '未获取到匹配的任务详情。')
        return
      }
      setNoticeMessage('success', `已刷新 ${successCount} 个任务详情。`)
      return
    }

    const loadedTasks = await fetchTaskList({ silent: true })
    if (loadedTasks.length === 0 && selectedCourseId) {
      await loadCourseProgress(selectedCourseId, true)
    }
    setNoticeMessage('success', '任务状态已刷新。')
  }, [fetchTaskDetail, fetchTaskList, loadCourseProgress, selectedCourseId, setNoticeMessage, taskIdsInput])

  const startCourseTask = useCallback(async (taskType = 'course') => {
    if (!selectedCourseId || startLoadingType) {
      if (!selectedCourseId) {
        setNoticeMessage('error', '请先选择课程。')
      }
      return
    }

    setStartLoadingType(taskType)
    const payload = {
      course_id: selectedCourseId,
      speed: Number(settings.speed) || 1,
      auto_answer: settings.autoAnswer
    }

    try {
      let resp
      try {
        resp = await requestZhihuishuApi(taskType === 'ai-course' ? '/tasks/ai-course' : '/tasks/course', {
          method: 'POST',
          body: JSON.stringify(payload)
        })
      } catch (_) {
        resp = await api(`${ZHIHUISHU_API_BASE}/course/start`, {
          method: 'POST',
          body: JSON.stringify(payload)
        })
      }

      const taskId = parseCourseId(resp?.task_id || resp?.data?.task_id || `${Date.now()}`)
      const selectedCourse = courses.find((course) => parseCourseId(course.courseId || course.id) === selectedCourseId)
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

      setActiveTaskId(taskId)
      setActiveTab('tasks')
      setNoticeMessage('success', pickMessage(resp) || '课程任务已启动。')
      await fetchTaskDetail(taskId, true)
    } catch (err) {
      setNoticeMessage('error', err.message || '启动课程失败。')
    } finally {
      setStartLoadingType('')
    }
  }, [courses, fetchTaskDetail, requestZhihuishuApi, selectedCourseId, setNoticeMessage, settings.autoAnswer, settings.speed, startLoadingType, upsertTaskRecord])

  const cancelTaskById = useCallback(async (taskId) => {
    if (!taskId || taskActionLoading || taskItemActionLoading) return
    setTaskItemActionLoading(taskId)
    try {
      const resp = await requestZhihuishuApi(`/tasks/${taskId}/cancel`, { method: 'POST' })
      const current = taskRecords.find((task) => task.taskId === taskId) || {}
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
  }, [activeTaskId, requestZhihuishuApi, setNoticeMessage, taskActionLoading, taskItemActionLoading, taskRecords, upsertTaskRecord])

  const pauseTask = async () => {
    if (taskActionLoading) return
    setTaskActionLoading('pause')

    try {
      const resp = await api(`${ZHIHUISHU_API_BASE}/pause`, { method: 'POST' })
      setTaskRecords((prev) => prev.map((task) => ({
        ...task,
        status: task.status === 'cancelled' ? task.status : 'paused',
        message: pickMessage(resp) || '任务已暂停。',
        updatedAt: new Date().toISOString()
      })))
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
      setTaskRecords((prev) => prev.map((task) => ({
        ...task,
        status: task.status === 'cancelled' ? task.status : 'running',
        message: pickMessage(resp) || '任务已恢复。',
        updatedAt: new Date().toISOString()
      })))
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
    setTaskActionLoading('cancel')

    try {
      const resp = await api(`${ZHIHUISHU_API_BASE}/cancel`, { method: 'POST' })
      setTaskRecords((prev) => prev.map((task) => ({
        ...task,
        status: 'cancelled',
        message: pickMessage(resp) || '任务已取消。',
        updatedAt: new Date().toISOString()
      })))
      setActiveTaskId('')
      setProgress(null)
      stopProgressPolling()
      setNoticeMessage('success', pickMessage(resp) || '任务已取消。')
    } catch (err) {
      setNoticeMessage('error', err.message || '取消任务失败。')
    } finally {
      setTaskActionLoading('')
    }
  }

  const pollQrStatus = useCallback(async (sessionId) => {
    try {
      const resp = await api(`${ZHIHUISHU_API_BASE}/login-status/${sessionId}`, { method: 'GET' })
      const nextStatus = String(resp?.status || 'pending')
      setQrStatus(nextStatus)
      setQrMessage(resp?.message || '等待扫码')

      if (nextStatus === 'success') {
        stopQrPolling()
        setZhihuishuLoggedIn(true)
        setNoticeMessage('success', '二维码登录成功，正在加载课程。')
        await Promise.all([loadCourses(true), loadConfigFromBackend(true), fetchTaskList({ silent: true })])
      }
      if (nextStatus === 'failed') {
        stopQrPolling()
      }
    } catch (err) {
      stopQrPolling()
      setQrStatus('failed')
      setQrError(err.message || '查询二维码状态失败。')
      setNoticeMessage('error', err.message || '查询二维码状态失败。')
    }
  }, [fetchTaskList, loadConfigFromBackend, loadCourses, setNoticeMessage, stopQrPolling])

  const startQrLogin = useCallback(async () => {
    if (qrLoading) return

    stopQrPolling()
    setQrLoading(true)
    setQrError('')
    setQrStatus('loading')
    setQrMessage('正在生成二维码...')
    setNoticeMessage('info', '正在创建二维码登录会话。')

    try {
      const resp = await api(`${ZHIHUISHU_API_BASE}/qr-login`, { method: 'POST' })
      const nextSessionId = resp?.session_id
      const nextQrCode = resp?.qr_code
      if (!nextSessionId || !nextQrCode) {
        throw new Error('二维码登录响应无效。')
      }

      setQrSessionId(nextSessionId)
      setQrCode(nextQrCode)
      setQrStatus(String(resp?.status || 'pending'))
      setQrMessage(resp?.message || '请使用智慧树 App 扫码。')
      setNoticeMessage('success', '二维码已生成，请尽快扫码。')
    } catch (err) {
      setQrStatus('failed')
      setQrError(err.message || '创建二维码会话失败。')
      setQrMessage('无法启动二维码登录。')
      setNoticeMessage('error', err.message || '创建二维码会话失败。')
    } finally {
      setQrLoading(false)
    }
  }, [qrLoading, setNoticeMessage, stopQrPolling])

  const submitPasswordLogin = async (event) => {
    event.preventDefault()
    if (passwordLoading) return

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
      if (!loggedIn) {
        if (!silent) {
          setNoticeMessage('info', '当前未登录智慧树。')
        }
        return statusPayload
      }

      const currentTask = normalizeTaskRecord(statusPayload?.current_task || {})
      if (currentTask) {
        upsertTaskRecord(currentTask)
        setActiveTaskId(currentTask.taskId)
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
  }, [requestZhihuishuApi, setNoticeMessage, upsertTaskRecord])

  const resetZhihuishuSession = useCallback(() => {
    stopQrPolling()
    stopProgressPolling()

    setZhihuishuLoggedIn(false)
    setLoginMethod('qr')

    setQrSessionId('')
    setQrCode('')
    setQrStatus('idle')
    setQrMessage('')
    setQrError('')

    setCourseGroups([])
    setCourses([])
    setSelectedCourseId('')
    setCourseDetail(null)
    setCourseStructure([])
    setVideos([])
    setProgress(null)
    setTaskRecords([])
    setActiveTaskId('')
    setTaskIdsInput('')

    setNoticeMessage('info', '已清理智慧树会话状态。')
  }, [setNoticeMessage, stopProgressPolling, stopQrPolling])

  const logoutZhihuishu = useCallback(async () => {
    try {
      const resp = await requestZhihuishuApi('/logout', { method: 'POST' })
      resetZhihuishuSession()
      setNoticeMessage('success', pickMessage(resp) || '智慧树会话已退出。')
    } catch (err) {
      setNoticeMessage('error', err.message || '智慧树退出失败。')
    }
  }, [requestZhihuishuApi, resetZhihuishuSession, setNoticeMessage])

  const logoutSystem = useCallback(async () => {
    try {
      await requestZhihuishuApi('/logout', { method: 'POST' })
    } catch (_) {
      // ignore backend logout errors during system logout
    }
    removeToken()
    navigate('/login', { replace: true })
  }, [navigate, requestZhihuishuApi])

  useEffect(() => {
    loadSettingsFromStorage()
  }, [loadSettingsFromStorage])

  useEffect(() => {
    if (!isAuthenticated()) {
      navigate('/login', { replace: true })
      return undefined
    }

    const storedActiveTaskId = readActiveTaskIdFromStorage()
    activeTaskStorageReadyRef.current = true

    void (async () => {
      try {
        await loadConfigFromBackend(true)
        const statusPayload = await loadZhihuishuStatus(true)
        if (statusPayload?.logged_in) {
          const [, loadedTasks] = await Promise.all([
            loadCourses(true),
            fetchTaskList({ silent: true, preferredTaskId: storedActiveTaskId })
          ])

          const normalizedStoredTaskId = parseCourseId(storedActiveTaskId)
          if (normalizedStoredTaskId) {
            const existsInList = loadedTasks.some((task) => task.taskId === normalizedStoredTaskId)
            if (existsInList) {
              setActiveTaskId(normalizedStoredTaskId)
            } else {
              const restoredTask = await fetchTaskDetail(normalizedStoredTaskId, true)
              if (!restoredTask?.taskId) {
                setActiveTaskId(loadedTasks[0]?.taskId || '')
              }
            }
          } else if (loadedTasks[0]?.taskId) {
            setActiveTaskId(loadedTasks[0].taskId)
          }
        } else {
          setActiveTaskId('')
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
    fetchTaskDetail,
    fetchTaskList,
    loadConfigFromBackend,
    loadCourses,
    loadZhihuishuStatus,
    navigate,
    readActiveTaskIdFromStorage,
    stopProgressPolling,
    stopQrPolling
  ])

  useEffect(() => {
    if (!activeTaskStorageReadyRef.current) return
    saveActiveTaskIdToStorage(activeTaskId)
  }, [activeTaskId, saveActiveTaskIdToStorage])

  useEffect(() => {
    if (!qrSessionId || qrStatus !== 'pending') return undefined

    stopQrPolling()
    qrPollRef.current = setInterval(() => {
      void pollQrStatus(qrSessionId)
    }, QR_POLL_INTERVAL_MS)

    return stopQrPolling
  }, [pollQrStatus, qrSessionId, qrStatus, stopQrPolling])

  useEffect(() => {
    if (!activeTaskId) {
      stopProgressPolling()
      return undefined
    }

    const pollSeconds = clampPollSeconds(settings.progressPollSeconds)
    stopProgressPolling()

    progressPollRef.current = setInterval(() => {
      void fetchTaskDetail(activeTaskId, true)
    }, pollSeconds * 1000)

    void fetchTaskDetail(activeTaskId, true)

    return stopProgressPolling
  }, [activeTaskId, fetchTaskDetail, settings.progressPollSeconds, stopProgressPolling])

  useEffect(() => {
    if (!selectedCourseId) {
      setCourseDetail(null)
      setCourseStructure([])
      setVideos([])
      return
    }
    void loadCourseDetail(selectedCourseId, true)
  }, [loadCourseDetail, selectedCourseId])

  const qrStatusText = useMemo(() => {
    if (qrStatus === 'idle') return '未开始'
    if (qrStatus === 'loading') return '加载中'
    if (qrStatus === 'pending') return '等待扫码'
    if (qrStatus === 'success') return '登录成功'
    if (qrStatus === 'failed') return '登录失败'
    return '未知状态'
  }, [qrStatus])

  const selectedCourse = useMemo(() => {
    if (!selectedCourseId) return null
    if (courseDetail && parseCourseId(courseDetail.courseId || courseDetail.id) === selectedCourseId) {
      return {
        ...courses.find((course) => parseCourseId(course.courseId || course.id) === selectedCourseId),
        ...courseDetail
      }
    }
    return courses.find((course) => parseCourseId(course.courseId || course.id) === selectedCourseId) || null
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

  if (booting) {
    return (
      <div className="min-h-screen overflow-x-hidden bg-background p-4">
        <div className={`mx-auto max-w-3xl ${GLASS_CARD_CLASS}`}>
          <div className="flex items-center gap-3 text-text">
            <Loader2 className="h-5 w-5 animate-spin text-primary" />
            <p>正在检查登录状态...</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen overflow-x-hidden bg-background p-4 md:p-6">
      <main className="mx-auto max-w-6xl space-y-6">
        <section className={GLASS_CARD_CLASS}>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="text-2xl font-bold text-text">智慧树学习助手</h1>
              <p className="text-sm text-text/70">登录、选课、任务控制、设置与状态管理一体化。</p>
            </div>
            <button
              type="button"
              className={`${ACTION_BUTTON_CLASS} bg-secondary/90 hover:bg-secondary`}
              onClick={() => navigate('/dashboard')}
            >
              返回控制台
            </button>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-5">
            {['login', 'courses', 'tasks', 'settings', 'status'].map((tab) => (
              <button
                key={tab}
                type="button"
                className={`${TAB_BUTTON_CLASS} ${activeTab === tab ? 'bg-primary text-white' : 'bg-white/70 text-text hover:bg-white'}`}
                onClick={() => setActiveTab(tab)}
              >
                {tab === 'login' ? '登录' : tab === 'courses' ? '课程' : tab === 'tasks' ? '任务' : tab === 'settings' ? '设置' : '状态/退出'}
              </button>
            ))}
          </div>
        </section>

        {notice.message && (
          <section
            className={`rounded-xl border p-3 text-sm transition-all duration-200 ${
              notice.type === 'success'
                ? 'border-green-500/30 bg-green-50 text-green-700'
                : notice.type === 'error'
                  ? 'border-red-500/30 bg-red-50 text-red-700'
                  : 'border-primary/20 bg-white/75 text-text'
            }`}
            role="status"
            aria-live="polite"
          >
            <p className="flex items-center gap-2">
              {notice.type === 'success' ? <CheckCircle2 className="h-4 w-4" /> : notice.type === 'error' ? <AlertCircle className="h-4 w-4" /> : <Loader2 className="h-4 w-4 animate-spin" />}
              {notice.message}
            </p>
          </section>
        )}

        {activeTab === 'login' && (
          <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className={`${GLASS_CARD_CLASS} space-y-4`}>
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-text">二维码登录</h2>
                <button
                  type="button"
                  className={`${ACTION_BUTTON_CLASS} bg-secondary/90 hover:bg-secondary`}
                  onClick={() => {
                    setLoginMethod('qr')
                    void startQrLogin()
                  }}
                  disabled={qrLoading}
                >
                  <span className="inline-flex items-center gap-2">
                    <RefreshCcw className="h-4 w-4" />
                    {qrLoading ? '生成中...' : '生成二维码'}
                  </span>
                </button>
              </div>

              <p className="text-sm text-text/70">{qrMessage || '请生成二维码并使用智慧树 App 扫码。'}</p>
              <div className="flex justify-center">
                {qrLoading && !qrCode && <div className="flex h-56 w-56 items-center justify-center rounded-2xl border border-white/30 bg-white/70"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>}
                {!qrLoading && qrCode && <img src={`data:image/png;base64,${qrCode}`} alt="智慧树二维码" className="h-56 w-56 rounded-2xl border border-white/30 bg-white object-contain shadow-sm" />}
              </div>
              <div className="rounded-xl border border-white/30 bg-white/70 p-3 text-sm text-text">
                <p className="flex items-center gap-2"><QrCode className="h-4 w-4 text-primary" />状态：{qrStatusText}</p>
                {qrError && <p className="mt-2 text-red-600">{qrError}</p>}
              </div>
            </div>

            <div className={`${GLASS_CARD_CLASS} space-y-4`}>
              <h2 className="text-lg font-bold text-text">账号密码登录</h2>
              <form className="space-y-4" onSubmit={submitPasswordLogin}>
                <Input id="zhs-username" label="账号" type="text" value={passwordForm.username} onChange={(event) => { setLoginMethod('password'); setPasswordForm((prev) => ({ ...prev, username: event.target.value })) }} required />
                <Input id="zhs-password" label="密码" type="password" value={passwordForm.password} onChange={(event) => { setLoginMethod('password'); setPasswordForm((prev) => ({ ...prev, password: event.target.value })) }} required />
                <button type="submit" className={`${ACTION_BUTTON_CLASS} w-full bg-primary hover:bg-primary/90`} disabled={passwordLoading}>{passwordLoading ? '登录中...' : '密码登录'}</button>
              </form>

              <div className={PANEL_CLASS}>
                <p className="text-sm text-text/80">当前登录方式：{loginMethod === 'qr' ? '二维码' : '账号密码'}</p>
                <p className="mt-2 text-sm text-text/80">智慧树状态：{zhihuishuLoggedIn ? '已登录' : '未登录'}</p>
              </div>
            </div>
          </section>
        )}
        {activeTab === 'courses' && (
          <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className={`${GLASS_CARD_CLASS} space-y-4`}>
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-text">课程与启动</h2>
                <button
                  type="button"
                  className={`${ACTION_BUTTON_CLASS} bg-secondary/90 hover:bg-secondary`}
                  onClick={() => {
                    void loadCourses(false)
                  }}
                  disabled={coursesLoading}
                >
                  {coursesLoading ? '刷新中...' : '刷新课程'}
                </button>
              </div>

              <div>
                <label htmlFor="zhs-course" className="mb-2 block text-sm font-medium text-text">分组课程</label>
                <select
                  id="zhs-course"
                  className={`${FIELD_CLASS} cursor-pointer`}
                  value={selectedCourseId}
                  onChange={(event) => setSelectedCourseId(event.target.value)}
                >
                  <option value="">请选择课程</option>
                  {courseGroups.map((group) => (
                    <optgroup key={group.group} label={`${group.group}（${group.courses.length}）`}>
                      {group.courses.map((course) => {
                        const id = parseCourseId(course.courseId || course.id)
                        const title = course.courseName || course.name || course.title || id
                        return <option key={`${group.group}-${id}`} value={id}>{title}</option>
                      })}
                    </optgroup>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="zhs-speed" className="mb-2 block text-sm font-medium text-text">学习倍速</label>
                  <select id="zhs-speed" className={`${FIELD_CLASS} cursor-pointer`} value={settings.speed} onChange={(event) => setSettings((prev) => ({ ...prev, speed: event.target.value }))}>
                    <option value="0.5">0.5x</option>
                    <option value="1.0">1.0x</option>
                    <option value="1.5">1.5x</option>
                    <option value="2.0">2.0x</option>
                  </select>
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-text">自动答题</label>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={settings.autoAnswer}
                    className={`relative min-h-[44px] min-w-[44px] w-16 rounded-full px-1 transition-all duration-200 cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary/40 ${settings.autoAnswer ? 'bg-primary' : 'bg-slate-300'}`}
                    onClick={() => setSettings((prev) => ({ ...prev, autoAnswer: !prev.autoAnswer }))}
                  >
                    <span className={`inline-block h-8 w-8 rounded-full bg-white transition-transform duration-200 ${settings.autoAnswer ? 'translate-x-7' : 'translate-x-0'}`} />
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <button
                  type="button"
                  className={`${ACTION_BUTTON_CLASS} bg-cta hover:bg-cta/90`}
                  onClick={() => {
                    void startCourseTask('course')
                  }}
                  disabled={!selectedCourseId || startLoadingType !== ''}
                >
                  <span className="inline-flex items-center gap-2">
                    <Play className="h-4 w-4" />
                    {startLoadingType === 'course' ? '启动中...' : '启动课程任务'}
                  </span>
                </button>
                <button
                  type="button"
                  className={`${ACTION_BUTTON_CLASS} bg-primary/90 hover:bg-primary`}
                  onClick={() => {
                    void startCourseTask('ai-course')
                  }}
                  disabled={!selectedCourseId || startLoadingType !== ''}
                >
                  <span className="inline-flex items-center gap-2">
                    <Play className="h-4 w-4" />
                    {startLoadingType === 'ai-course' ? '启动中...' : '启动 AI 任务'}
                  </span>
                </button>
              </div>

              <div>
                <button
                  type="button"
                  className={`${ACTION_BUTTON_CLASS} w-full bg-secondary/90 hover:bg-secondary`}
                  onClick={() => {
                    void loadVideos(selectedCourseId)
                  }}
                  disabled={!selectedCourseId || videosLoading}
                >
                  <span className="inline-flex items-center gap-2">
                    <List className="h-4 w-4" />
                    {videosLoading ? '加载中...' : '查看视频列表/结构'}
                  </span>
                </button>
              </div>
            </div>

            <div className={`${GLASS_CARD_CLASS} space-y-4`}>
              <h2 className="text-lg font-bold text-text">课程详情</h2>
              {!selectedCourseId ? (
                <p className="text-sm text-text/70">请选择课程查看详情与进度。</p>
              ) : (
                <div className="space-y-3">
                  <div className={PANEL_CLASS}>
                    <p className="text-sm text-text/70">课程名称</p>
                    <p className="mt-1 font-semibold text-text">{selectedCourse?.courseName || selectedCourse?.name || selectedCourse?.title || selectedCourseId}</p>
                    <p className="mt-2 text-xs text-text/60">课程 ID：{selectedCourseId}</p>
                    <p className="mt-1 text-xs text-text/60">分组：{selectedCourse?._groupName || selectedCourse?.semesterName || selectedCourse?.termName || '未分类'}</p>
                    {courseDetailLoading && <p className="mt-2 text-xs text-text/70">正在加载课程详情...</p>}
                  </div>

                  <div className={PANEL_CLASS}>
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-medium text-text">学习进度</p>
                      <button
                        type="button"
                        className={`${ACTION_BUTTON_CLASS} bg-secondary/90 hover:bg-secondary`}
                        onClick={() => {
                          if (activeTaskId) {
                            void fetchTaskDetail(activeTaskId, false)
                          } else {
                            void loadCourseProgress(selectedCourseId, false)
                          }
                        }}
                        disabled={!selectedCourseId || progressLoading}
                      >
                        {progressLoading ? '刷新中...' : '刷新进度'}
                      </button>
                    </div>
                    <p className="mt-3 text-sm text-text/80">状态：{progress?.status || '未获取'}</p>
                    <p className="mt-1 text-sm text-text/80">消息：{progress?.message || '暂无'}</p>
                    <p className="mt-1 text-sm text-text/80">当前视频：{selectedCourseProgress.currentVideo || '暂无'}</p>
                    <p className="mt-1 text-sm text-text/80">实时进度：{selectedCourseProgress.completed}/{selectedCourseProgress.total}（{Math.round(selectedCourseProgress.percentage)}%）</p>
                    <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200/80">
                      <div className="h-full rounded-full bg-cta transition-all duration-200" style={{ width: `${selectedCourseProgress.percentage}%` }} />
                    </div>
                    <p className="mt-2 text-xs text-text/60">失败：{selectedCourseProgress.failed}{selectedCourseProgress.estimatedTime ? ` · 预计剩余：${selectedCourseProgress.estimatedTime}` : ""}</p>
                  </div>

                  <div className={PANEL_CLASS}>
                    <p className="text-sm font-medium text-text">课程结构</p>
                    {courseStructure.length === 0 ? (
                      <p className="mt-2 text-sm text-text/70">暂无结构数据，可尝试“查看视频列表/结构”。</p>
                    ) : (
                      <ul className="mt-2 max-h-40 space-y-2 overflow-y-auto pr-1 text-sm text-text/80">
                        {courseStructure.map((section, index) => (
                          <li key={`${section.id || index}`} className="rounded-lg border border-white/30 bg-white/70 px-3 py-2">
                            <p className="font-medium text-text">{section.title || `结构 ${index + 1}`}</p>
                            <p className="text-xs text-text/70">视频数：{Array.isArray(section.videos) ? section.videos.length : 0}</p>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <div className={PANEL_CLASS}>
                    <p className="text-sm font-medium text-text">视频列表</p>
                    {videos.length === 0 ? (
                      <p className="mt-2 text-sm text-text/70">尚未加载视频任务。</p>
                    ) : (
                      <ul className="mt-2 max-h-48 space-y-2 overflow-y-auto pr-1 text-sm text-text/80">
                        {videos.map((video, index) => {
                          const title = video.name || video.title || video.videoName || `视频 ${index + 1}`
                          const status = video.status || 'unknown'
                          return (
                            <li key={`${title}-${index}`} className="rounded-lg border border-white/30 bg-white/70 px-3 py-2">
                              <p className="font-medium text-text">{title}</p>
                              <p className="text-xs text-text/70">状态：{status}</p>
                              {video.sectionTitle && <p className="text-xs text-text/70">章节：{video.sectionTitle}</p>}
                            </li>
                          )
                        })}
                      </ul>
                    )}
                  </div>
                </div>
              )}
            </div>
          </section>
        )}

        {activeTab === 'tasks' && (
          <section className="space-y-6">
            <div className={GLASS_CARD_CLASS}>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <h2 className="text-lg font-bold text-text">任务控制</h2>
                <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
                  <button type="button" className={`${ACTION_BUTTON_CLASS} bg-secondary/90 hover:bg-secondary`} onClick={refreshTaskList} disabled={progressLoading}><span className="inline-flex items-center gap-2"><RefreshCcw className="h-4 w-4" />刷新列表</span></button>
                  <button type="button" className={`${ACTION_BUTTON_CLASS} bg-primary/90 hover:bg-primary`} onClick={pauseTask} disabled={taskActionLoading !== ''}><span className="inline-flex items-center gap-2"><Pause className="h-4 w-4" />{taskActionLoading === 'pause' ? '暂停中...' : '暂停'}</span></button>
                  <button type="button" className={`${ACTION_BUTTON_CLASS} bg-secondary/90 hover:bg-secondary`} onClick={resumeTask} disabled={taskActionLoading !== ''}><span className="inline-flex items-center gap-2"><Play className="h-4 w-4" />{taskActionLoading === 'resume' ? '恢复中...' : '恢复'}</span></button>
                  <button type="button" className={`${ACTION_BUTTON_CLASS} bg-red-500 hover:bg-red-600`} onClick={cancelTask} disabled={taskActionLoading !== ''}><span className="inline-flex items-center gap-2"><X className="h-4 w-4" />{taskActionLoading === 'cancel' ? '取消中...' : '取消'}</span></button>
                </div>
              </div>

              <div className="mt-4">
                <label htmlFor="zhs-task-ids" className="mb-2 block text-sm font-medium text-text">
                  按任务 ID 刷新（可选，支持逗号/空格分隔）
                </label>
                <input
                  id="zhs-task-ids"
                  className={FIELD_CLASS}
                  value={taskIdsInput}
                  onChange={(event) => setTaskIdsInput(event.target.value)}
                  placeholder="例如：task_a, task_b"
                />
              </div>
            </div>

            <div className={GLASS_CARD_CLASS}>
              <h3 className="text-base font-semibold text-text">任务列表</h3>
              {sortedTasks.length === 0 ? (
                <p className="py-8 text-center text-sm text-text/70">暂无任务记录，启动课程后会显示在这里。</p>
              ) : (
                <div className="mt-4 space-y-3">
                  {sortedTasks.map((task) => (
                    <div key={task.taskId} className={PANEL_CLASS}>
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <div>
                          <p className="font-semibold text-text">{task.courseName}</p>
                          <p className="mt-1 text-xs text-text/70">任务 ID：{task.taskId}</p>
                        </div>
                        <div className="text-sm text-text/80">
                          <p>类型：{task.taskType || 'course'}</p>
                          <p>状态：{task.status || 'unknown'}</p>
                          <p className="mt-1">更新时间：{new Date(task.updatedAt || task.startedAt).toLocaleString()}</p>
                        </div>
                      </div>
                      <p className="mt-2 text-sm text-text/80">消息：{task.message || '暂无'}</p>
                      <p className="mt-1 text-sm text-text/80">当前视频：{task.currentTask || '暂无'}</p>
                      <p className="mt-1 text-sm text-text/80">
                        进度：{task.completed || 0}/{task.total || 0}（{Math.round(Number(task.percentage || 0))}%）
                      </p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          type="button"
                          className={`${ACTION_BUTTON_CLASS} bg-secondary/90 hover:bg-secondary`}
                          onClick={() => {
                            void fetchTaskDetail(task.taskId, false)
                          }}
                          disabled={taskActionLoading !== '' || taskItemActionLoading === task.taskId}
                        >
                          查看详情
                        </button>
                        <button
                          type="button"
                          className={`${ACTION_BUTTON_CLASS} bg-red-500 hover:bg-red-600`}
                          onClick={() => {
                            void cancelTaskById(task.taskId)
                          }}
                          disabled={taskActionLoading !== '' || taskItemActionLoading === task.taskId}
                        >
                          {taskItemActionLoading === task.taskId ? '取消中...' : '取消该任务'}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}

        {activeTab === 'settings' && (
          <section className={GLASS_CARD_CLASS}>
            <h2 className="text-lg font-bold text-text">配置保存</h2>
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label htmlFor="settings-speed" className="mb-2 block text-sm font-medium text-text">默认学习倍速</label>
                <select id="settings-speed" className={`${FIELD_CLASS} cursor-pointer`} value={settings.speed} onChange={(event) => setSettings((prev) => ({ ...prev, speed: event.target.value }))}>
                  <option value="0.5">0.5x</option>
                  <option value="1.0">1.0x</option>
                  <option value="1.5">1.5x</option>
                  <option value="2.0">2.0x</option>
                </select>
              </div>

              <div>
                <label htmlFor="settings-poll" className="mb-2 block text-sm font-medium text-text">进度轮询间隔（秒）</label>
                <input id="settings-poll" type="number" min={String(MIN_PROGRESS_POLL_SECONDS)} max={String(MAX_PROGRESS_POLL_SECONDS)} value={settings.progressPollSeconds} onChange={(event) => setSettings((prev) => ({ ...prev, progressPollSeconds: clampPollSeconds(event.target.value) }))} className={FIELD_CLASS} />
              </div>
            </div>

            <div className="mt-4 flex items-center justify-between rounded-xl border border-white/30 bg-white/70 px-4 py-3">
              <div>
                <p className="font-medium text-text">默认自动答题</p>
                <p className="mt-1 text-sm text-text/70">启动课程时默认启用自动答题。</p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={settings.autoAnswer}
                className={`relative min-h-[44px] min-w-[44px] w-16 rounded-full px-1 transition-all duration-200 cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary/40 ${settings.autoAnswer ? 'bg-primary' : 'bg-slate-300'}`}
                onClick={() => setSettings((prev) => ({ ...prev, autoAnswer: !prev.autoAnswer }))}
              >
                <span className={`inline-block h-8 w-8 rounded-full bg-white transition-transform duration-200 ${settings.autoAnswer ? 'translate-x-7' : 'translate-x-0'}`} />
              </button>
            </div>

            <div className="mt-4">
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className={`${ACTION_BUTTON_CLASS} bg-secondary/90 hover:bg-secondary`}
                  onClick={() => {
                    void loadConfigFromBackend(false)
                  }}
                  disabled={settingsSaving}
                >
                  从后端读取
                </button>
                <button
                  type="button"
                  className={`${ACTION_BUTTON_CLASS} bg-cta hover:bg-cta/90`}
                  onClick={() => {
                    void saveSettings(settings)
                  }}
                  disabled={settingsSaving}
                >
                  {settingsSaving ? '保存中...' : '保存配置'}
                </button>
              </div>
            </div>
          </section>
        )}

        {activeTab === 'status' && (
          <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className={`${GLASS_CARD_CLASS} space-y-4`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-lg font-bold text-text">当前状态</h2>
                <button
                  type="button"
                  className={`${ACTION_BUTTON_CLASS} bg-secondary/90 hover:bg-secondary`}
                  onClick={() => {
                    void loadZhihuishuStatus(false)
                  }}
                >
                  同步状态
                </button>
              </div>
              <div className={PANEL_CLASS}>
                <p className="text-sm text-text/80">智慧树登录：{zhihuishuLoggedIn ? '已登录' : '未登录'}</p>
                <p className="mt-2 text-sm text-text/80">二维码状态：{qrStatusText}</p>
                <p className="mt-2 text-sm text-text/80">活跃任务 ID：{activeTaskId || '无'}</p>
                <p className="mt-2 text-sm text-text/80">任务总数：{taskRecords.length}</p>
                <p className="mt-2 text-sm text-text/80">进度轮询：{clampPollSeconds(settings.progressPollSeconds)} 秒</p>
              </div>

              <div className={PANEL_CLASS}>
                <p className="text-sm text-text/80">最近进度</p>
                <p className="mt-2 text-sm text-text/80">状态：{activeTaskSummary.status}</p>
                <p className="mt-1 text-sm text-text/80">消息：{activeTaskSummary.message}</p>
                <p className="mt-1 text-sm text-text/80">活跃课程：{activeTaskSummary.courseName || '暂无'}</p>
                <p className="mt-1 text-sm text-text/80">当前视频：{activeTaskSummary.currentVideo || '暂无'}</p>
                <p className="mt-1 text-sm text-text/80">实时进度：{activeTaskSummary.completed}/{activeTaskSummary.total}（{Math.round(activeTaskSummary.percentage)}%）</p>
                <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200/80">
                  <div className="h-full rounded-full bg-primary transition-all duration-200" style={{ width: `${activeTaskSummary.percentage}%` }} />
                </div>
                <p className="mt-2 text-xs text-text/60">失败：{activeTaskSummary.failed}{activeTaskSummary.estimatedTime ? ` · 预计剩余：${activeTaskSummary.estimatedTime}` : ""}</p>
              </div>
            </div>

            <div className={`${GLASS_CARD_CLASS} space-y-4`}>
              <h2 className="text-lg font-bold text-text">退出与清理</h2>
              <button type="button" className={`${ACTION_BUTTON_CLASS} w-full bg-primary/90 hover:bg-primary`} onClick={logoutZhihuishu}>退出智慧树会话（后端）</button>
              <button type="button" className={`${ACTION_BUTTON_CLASS} w-full bg-secondary/90 hover:bg-secondary`} onClick={resetZhihuishuSession}>清理智慧树会话状态</button>
              <button type="button" className={`${ACTION_BUTTON_CLASS} w-full bg-red-500 hover:bg-red-600`} onClick={() => { void logoutSystem() }}>系统退出登录</button>
              <div className="rounded-xl border border-white/30 bg-white/70 p-4 text-sm text-text/70">
                <p>说明：</p>
                <p className="mt-2">1. 清理会话仅重置当前页面状态，不会删除已保存设置。</p>
                <p className="mt-1">2. 退出智慧树会调用 `/course/zhihuishu/logout` 并取消相关任务。</p>
                <p className="mt-1">3. 系统退出会清除 Token 并返回登录页。</p>
              </div>
            </div>
          </section>
        )}

        <footer className="pb-2 text-xs text-text/60">
          <p className="flex items-center gap-2"><Clock className="h-3.5 w-3.5" />交互按钮均为 44px+ 点击目标，支持键盘聚焦与 200ms 过渡动画。</p>
        </footer>
      </main>
    </div>
  )
}

