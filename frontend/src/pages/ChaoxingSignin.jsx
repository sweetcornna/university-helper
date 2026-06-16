import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { ChevronDown, Loader2, Camera, Map, MapPin, RefreshCw, Upload } from 'lucide-react'

import { getToken, removeToken } from '../utils/auth'

import { Button, Input, MultiSelect, Select, useToast } from '../components'

// Lazy-load the map picker (pulls in ~150KB of leaflet) only when the user
// opens it, so the initial signin page stays light on mobile.
const BaiduMapPickerModal = lazy(() => import('../components/BaiduMapPickerModal'))

import {
  CHAOXING_API_BASE,
  TOKEN_ERROR_PATTERN,
  GLASS_CARD_CLASS,
  GLASS_PANEL_CLASS,
  parsePayload,
  pickMessage,
  normalizeSignTypeForApi,
  shouldUseLocationParams,
  fileToBase64,
  decodeQrCodeFromFile,
  normalizeBackgroundTaskHistory,
  upsertBackgroundTaskHistory,
  isBackgroundTaskRunning,
  safeStringify,
  buildCourseSelector,
  buildClassSelector,
  getCourseDisplayName,
  getClassDisplayName,
  normalizeCourseText,
  parseTaskTimestamp,
} from './chaoxing-signin/utils'

import useBackgroundTasks from './chaoxing-signin/hooks/useBackgroundTasks'
import useAutoSignin from './chaoxing-signin/hooks/useAutoSignin'
import useLocationServices from './chaoxing-signin/hooks/useLocationServices'

import StatsCards from './chaoxing-signin/components/StatsCards'
import TasksTab from './chaoxing-signin/components/TasksTab'
import HistoryTab from './chaoxing-signin/components/HistoryTab'
import ConfigTab from './chaoxing-signin/components/ConfigTab'
import AutoSigninBanner from './chaoxing-signin/components/AutoSigninBanner'

import { readLastUsername, saveLastUsername } from '../utils/chaoxingCreds'

export default function ChaoxingSignin() {
  const navigate = useNavigate()

  const ensureAccessTokenRef = useRef(null)

  const redirectToLoginRef = useRef(null)

  const redirectingRef = useRef(false)

  const setTodayStatsRef = useRef(null)

  // Live-log ref so the pane sticks to the newest line.
  const logContainerRef = useRef(null)

  const toast = useToast()

  const [submitting, setSubmitting] = useState(false)

  const [resultMessage, setResultMessage] = useState('')

  const [resultType, setResultType] = useState('info')

  const [activeTab, setActiveTab] = useState('signin')

  // In 通用模式(all) the type-specific fields are optional (the backend
  // auto-matches the teacher's type), so they stay collapsed behind this
  // disclosure instead of flooding the form with all six groups at once.
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const [courses, setCourses] = useState([])

  const [classSubjects, setClassSubjects] = useState([])

  const [signinTasks, setSigninTasks] = useState([])

  const [signinHistory, setSigninHistory] = useState([])

  const [backgroundTaskHistory, setBackgroundTaskHistory] = useState([])

  const [form, setForm] = useState(() => ({
    // Recall the last-used account so returning users don't retype it every
    // visit. Only the username is persisted — never the password.
    username: readLastUsername(),

    password: '',

    selectedCourseIds: [],

    selectedClassIds: [],

    signType: 'all',

    latitude: '',

    longitude: '',

    address: '',

    altitude: '100',

    photoFile: null,

    qrCode: '',

    qrCodeFile: null,

    qrDecodeStatus: '',

    signCode: '',

    gesturePattern: '',
  }))

  const ensureAccessToken = useCallback(() => {
    return getToken() || null
  }, [])

  const redirectToLogin = useCallback(
    (message = '登录已过期，请重新登录。') => {
      if (!redirectingRef.current) {
        redirectingRef.current = true

        removeToken()

        navigate('/login', { replace: true })
      }

      throw new Error(message)
    },
    [navigate]
  )

  ensureAccessTokenRef.current = ensureAccessToken

  redirectToLoginRef.current = redirectToLogin

  const requestChaoxingApi = useCallback(
    async (path, body, options = {}) => {
      if (redirectingRef.current) {
        throw new Error('正在跳转到登录页...')
      }

      const token = ensureAccessTokenRef.current()

      if (!token) {
        redirectToLoginRef.current('登录态失效，请重新登录。')
      }

      const hasBody = body !== undefined && body !== null

      const isFormData = body instanceof FormData

      const method = options.method || (hasBody ? 'POST' : 'GET')

      const headers = {
        ...(options.headers || {}),

        Authorization: `Bearer ${token}`,
      }

      if (hasBody && !isFormData && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json'
      }

      const response = await fetch(`${CHAOXING_API_BASE}${path}`, {
        ...options,

        method,

        headers,

        body: hasBody ? (isFormData ? body : JSON.stringify(body)) : undefined,
      })

      const payload = await parsePayload(response)

      const message = pickMessage(payload)

      const code = payload?.code || payload?.error_code

      const isAuthFailure =
        response.status === 401 ||
        response.status === 403 ||
        code === 'AUTH_TOKEN_EXPIRED' ||
        code === 'AUTH_INVALID_TOKEN' ||
        (response.status === 200 &&
          payload?.status === false &&
          TOKEN_ERROR_PATTERN.test(message || ''))

      if (isAuthFailure) {
        redirectToLogin('登录已过期，请重新登录。')
      }

      if (!response.ok) {
        throw new Error(message || `请求失败（${response.status}）`)
      }

      if (payload?.status === false) {
        throw new Error(message || '请求失败')
      }

      return payload
    },

    [redirectToLogin]
  )

  // ── Hooks ──────────────────────────────────────────────────────────────────

  const backgroundTasks = useBackgroundTasks(requestChaoxingApi)
  const {
    taskId,
    setTaskId,
    taskStatus,
    setTaskStatus,
    logs,
    setLogs,
    statusLoading,
    refreshTaskStatus,
    openBackgroundTask,
    stopPolling,
  } = backgroundTasks

  const locationServices = useLocationServices(requestChaoxingApi, setForm)
  const {
    latestAddressRef,
    geocodeLoading,
    geocodeMessage,
    geocodeStatus,
    setGeocodeStatus,
    setGeocodeMessage,
    placeSearchLoading,
    placeSearchResults,
    placeSearchMessage,
    isMapPickerOpen,
    setIsMapPickerOpen,
    applyResolvedLocation,
    useCurrentLocation,
    resolveLocationCoordinates,
    searchLocationCandidates,
    choosePlaceSearchResult,
  } = locationServices

  // Route every result through the shared toast so success/failure is visible
  // no matter which tab the user is on (previously it was buried at the bottom
  // of the signin form), then clear it so a recurring message re-announces.
  useEffect(() => {
    if (resultMessage) {
      toast.notify(resultType, resultMessage)
      setResultMessage('')
    }
  }, [resultMessage, resultType, toast])

  // Keep the live-log pane pinned to the newest line.
  useEffect(() => {
    const el = logContainerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [logs])

  // Remember the account for next visit (username only).
  useEffect(() => {
    saveLastUsername(form.username)
  }, [form.username])

  // ── Callbacks that depend on requestChaoxingApi ────────────────────────────

  const fetchCourses = useCallback(async () => {
    try {
      const resp = await requestChaoxingApi('/courses')

      setCourses(resp?.data || [])
    } catch (err) {
      if (!redirectingRef.current) {
        console.error('Failed to fetch courses:', err)
      }
    }
  }, [requestChaoxingApi])

  const fetchClasses = useCallback(async () => {
    try {
      const resp = await requestChaoxingApi('/classes')

      setClassSubjects(resp?.data || resp?.classes || [])
    } catch (err) {
      if (!redirectingRef.current) {
        console.error('Failed to fetch class subjects:', err)
      }
    }
  }, [requestChaoxingApi])

  const fetchSigninTasks = useCallback(async () => {
    try {
      const resp = await requestChaoxingApi('/tasks')

      setSigninTasks(resp?.data || [])
    } catch (err) {
      if (!redirectingRef.current) {
        console.error('Failed to fetch signin tasks:', err)
      }
    }
  }, [requestChaoxingApi])

  const fetchSigninHistory = useCallback(async () => {
    try {
      const resp = await requestChaoxingApi('/history')

      setSigninHistory(resp?.data || [])

      const today = new Date().toDateString()

      const todayRecords = (resp?.data || []).filter(
        (r) => new Date(r.timestamp).toDateString() === today
      )

      if (setTodayStatsRef.current) {
        setTodayStatsRef.current({
          total: todayRecords.length,

          success: todayRecords.filter((r) => r.status === 'success').length,

          failed: todayRecords.filter((r) => r.status === 'failed').length,
        })
      }
    } catch (err) {
      if (!redirectingRef.current) {
        console.error('Failed to fetch signin history:', err)
      }
    }
  }, [requestChaoxingApi])

  const fetchBackgroundTaskHistory = useCallback(async () => {
    try {
      const resp = await requestChaoxingApi('/task-list')

      const normalizedTasks = normalizeBackgroundTaskHistory(resp)

      setBackgroundTaskHistory(normalizedTasks)

      return normalizedTasks
    } catch (err) {
      if (!redirectingRef.current) {
        console.error('Failed to fetch background tasks:', err)
      }

      return []
    }
  }, [requestChaoxingApi])

  const buildSigninPayload = useCallback(
    (courseId = null, signTypeOverride = null) => {
      const signType = signTypeOverride || form.signType

      const payload = {
        username: form.username.trim(),

        password: form.password,

        sign_type: normalizeSignTypeForApi(signType),

        course_id: courseId,
      }

      if (shouldUseLocationParams(signType)) {
        if (form.latitude) payload.latitude = form.latitude

        if (form.longitude) payload.longitude = form.longitude

        if (form.address) payload.address = form.address

        if (form.altitude !== '') payload.altitude = form.altitude
      }

      if ((signType === 'qrcode' || signType === 'all') && form.qrCode.trim()) {
        payload.qr_code = form.qrCode.trim()
      }

      if ((signType === 'code' || signType === 'all') && form.signCode.trim()) {
        payload.sign_code = form.signCode.trim()
      }

      if ((signType === 'gesture' || signType === 'all') && form.gesturePattern.trim()) {
        payload.gesture = form.gesturePattern.trim()
      }

      return { payload, signType }
    },
    [form]
  )

  const applySigninAssets = useCallback(
    async (payload, signType) => {
      if (signType === 'photo' && !form.photoFile) {
        throw new Error('拍照签到需要先上传图片。')
      }

      if (signType === 'qrcode' && !payload.qr_code) {
        throw new Error('二维码签到需要提供二维码内容，请上传二维码图片或手动输入。')
      }

      if (signType === 'gesture' && !payload.gesture) {
        throw new Error('手势签到需要输入手势编码。')
      }

      if (signType === 'code' && !payload.sign_code) {
        throw new Error('签到码签到需要输入签到码。')
      }

      if (form.photoFile && (signType === 'photo' || signType === 'all')) {
        payload.photo_base64 = await fileToBase64(form.photoFile)
      }

      return payload
    },
    [form.photoFile]
  )

  const executeSignin = useCallback(
    async (courseId = null, signTypeOverride = null, options = {}) => {
      const silent = Boolean(options.silent)

      if (!silent) {
        setSubmitting(true)

        setResultMessage('')
      }

      try {
        const username = form.username.trim()

        if (!username || !form.password) {
          throw new Error('请输入账号和密码。')
        }

        const { payload, signType } = buildSigninPayload(courseId, signTypeOverride)

        await applySigninAssets(payload, signType)

        const resp = await requestChaoxingApi('/sign', payload)

        const message = pickMessage(resp) || '签到成功。'

        if (!silent) {
          setResultType('success')

          setResultMessage(message)
        }

        await fetchSigninHistory()

        return { status: true, message }
      } catch (err) {
        const message = err.message || '签到失败。'

        if (!silent) {
          setResultType('error')

          setResultMessage(message)
        }

        return { status: false, message }
      } finally {
        if (!silent) {
          setSubmitting(false)
        }
      }
    },
    [
      applySigninAssets,
      buildSigninPayload,
      fetchSigninHistory,
      form.password,
      form.username,
      requestChaoxingApi,
    ]
  )

  // ── Auto-signin hook (depends on executeSignin) ────────────────────────────

  const autoSigninHook = useAutoSignin(form, executeSignin, requestChaoxingApi, {
    setResultType,
    setResultMessage,
    setSigninTasks,
    redirectingRef,
  })
  const {
    autoSignin,
    setAutoSignin,
    autoSignFilter,
    setAutoSignFilter,
    checkInterval,
    setCheckInterval,
    nextCheckCountdown,
    todayStats,
    stopAutoCheck,
  } = autoSigninHook

  setTodayStatsRef.current = autoSigninHook.setTodayStats

  const handleQrCodeFileUpload = useCallback(async (file) => {
    if (!file) return
    setForm((prev) => ({ ...prev, qrCodeFile: file, qrDecodeStatus: '解码中...' }))
    try {
      const decoded = await decodeQrCodeFromFile(file)
      setForm((prev) => ({ ...prev, qrCode: decoded, qrDecodeStatus: `解码成功` }))
    } catch (err) {
      setForm((prev) => ({ ...prev, qrDecodeStatus: err.message }))
    }
  }, [])

  // ── Bootstrap effect ───────────────────────────────────────────────────────
  // Route guarding lives in App.jsx (PrivateRoute).

  useEffect(() => {
    redirectingRef.current = false

    let cancelled = false

    const bootstrap = async () => {
      const token = ensureAccessToken()

      if (cancelled) return

      if (!token) {
        navigate('/login', { replace: true })

        return
      }

      const results = await Promise.allSettled([
        fetchCourses(),

        fetchClasses(),

        fetchSigninTasks(),

        fetchSigninHistory(),

        fetchBackgroundTaskHistory(),
      ])

      if (cancelled) return

      const backgroundTasksResult = results[4]

      if (backgroundTasksResult.status !== 'fulfilled') return

      const bgTasks = Array.isArray(backgroundTasksResult.value) ? backgroundTasksResult.value : []

      if (bgTasks.length === 0) return

      const runningTask = bgTasks.find((task) => isBackgroundTaskRunning(task.status))

      const latestTask = runningTask || bgTasks[0]

      if (latestTask?.taskId) {
        await openBackgroundTask(latestTask.taskId, {
          setResultType,
          setResultMessage,
          setBackgroundTaskHistory,
        })
      }
    }

    bootstrap()

    return () => {
      cancelled = true

      stopPolling()

      stopAutoCheck()
    }
  }, [
    ensureAccessToken,
    navigate,
    stopPolling,
    stopAutoCheck,
    fetchCourses,
    fetchClasses,
    fetchSigninTasks,
    fetchSigninHistory,
    fetchBackgroundTaskHistory,
    openBackgroundTask,
  ])

  const courseOptions = useMemo(() => {
    const source = Array.isArray(courses) ? courses : []

    const seen = new Set()

    const options = []

    source.forEach((course, index) => {
      const id = buildCourseSelector(course)

      if (!id || seen.has(id)) return

      seen.add(id)

      options.push({
        id,

        name: getCourseDisplayName(course, `课程 ${index + 1}`),
      })
    })

    return options
  }, [courses])

  const classOptions = useMemo(() => {
    const source = Array.isArray(classSubjects) ? classSubjects : []

    const seen = new Set()

    const options = []

    source.forEach((subject, index) => {
      const id = buildClassSelector(subject)

      const classId = normalizeCourseText(
        subject?.classSubjectId ||
          subject?.subjectId ||
          subject?.classId ||
          subject?.clazzId ||
          subject?.class_id ||
          subject?.clazz_id
      )

      const rawCourseId = normalizeCourseText(
        subject?.rawCourseId || subject?.courseId || subject?.course_id
      )

      const courseSelector = buildCourseSelector(subject)

      const key = id || classId || `${rawCourseId}-${index}`

      if (!key || seen.has(key)) return

      seen.add(key)

      options.push({
        id: key,

        classId: classId || key,

        courseId: rawCourseId,

        courseSelector,

        name: getClassDisplayName(subject, `班级 ${index + 1}`),
      })
    })

    return options
  }, [classSubjects])

  useEffect(() => {
    setForm((prev) => {
      if (!Array.isArray(prev.selectedCourseIds) || prev.selectedCourseIds.length === 0) {
        return prev
      }

      const validIds = new Set(courseOptions.map((course) => course.id))

      const nextSelected = prev.selectedCourseIds.filter((id) => validIds.has(id))

      const unchanged =
        nextSelected.length === prev.selectedCourseIds.length &&
        nextSelected.every((id, index) => id === prev.selectedCourseIds[index])

      if (unchanged) return prev

      return { ...prev, selectedCourseIds: nextSelected }
    })
  }, [courseOptions])

  useEffect(() => {
    setForm((prev) => {
      if (!Array.isArray(prev.selectedClassIds) || prev.selectedClassIds.length === 0) {
        return prev
      }

      const validIds = new Set(classOptions.map((subject) => subject.id))

      const nextSelected = prev.selectedClassIds.filter((id) => validIds.has(id))

      const unchanged =
        nextSelected.length === prev.selectedClassIds.length &&
        nextSelected.every((id, index) => id === prev.selectedClassIds[index])

      if (unchanged) return prev

      return { ...prev, selectedClassIds: nextSelected }
    })
  }, [classOptions])

  const executeClassSignin = useCallback(
    async (classOption, signTypeOverride = null, options = {}) => {
      const silent = Boolean(options.silent)

      if (!silent) {
        setSubmitting(true)

        setResultMessage('')
      }

      try {
        const username = form.username.trim()

        if (!username || !form.password) {
          throw new Error('请输入账号和密码。')
        }

        if (!classOption?.classId) {
          throw new Error('请选择有效的班级。')
        }

        const { payload, signType } = buildSigninPayload(null, signTypeOverride)

        delete payload.course_id

        payload.class_id = classOption.classId

        if (classOption.courseSelector) payload.course_id = classOption.courseSelector

        if (classOption.courseId && !payload.course_id) payload.course_id = classOption.courseId

        await applySigninAssets(payload, signType)

        const resp = await requestChaoxingApi('/class-sign', payload)

        const message = pickMessage(resp) || '班级签到成功。'

        if (!silent) {
          setResultType('success')

          setResultMessage(message)
        }

        await fetchSigninHistory()

        return { status: true, message }
      } catch (err) {
        const message = err.message || '班级签到失败。'

        if (!silent) {
          setResultType('error')

          setResultMessage(message)
        }

        return { status: false, message }
      } finally {
        if (!silent) {
          setSubmitting(false)
        }
      }
    },
    [
      applySigninAssets,
      buildSigninPayload,
      fetchSigninHistory,
      form.password,
      form.username,
      requestChaoxingApi,
    ]
  )

  const executeSelectedClassSignin = useCallback(async () => {
    if (submitting) return

    const selectedClassOptions = form.selectedClassIds
      .map((id) => classOptions.find((subject) => subject.id === id))
      .filter(Boolean)

    if (selectedClassOptions.length === 0) {
      setResultType('error')

      setResultMessage('请选择班级后再执行班级签到。')

      return
    }

    if (selectedClassOptions.length !== form.selectedClassIds.length) {
      setResultType('error')

      setResultMessage('选中的班级无效，请重新选择后再试。')

      return
    }

    setSubmitting(true)

    setResultMessage('')

    try {
      let success = 0

      const failed = []

      for (const classOption of selectedClassOptions) {
        const result = await executeClassSignin(classOption, form.signType, { silent: true })

        if (result.status) {
          success += 1
        } else {
          failed.push(`${classOption.name}：${result.message}`)
        }
      }

      if (failed.length > 0) {
        setResultType(success > 0 ? 'info' : 'error')

        setResultMessage(
          `班级签到完成，成功 ${success} 个，失败 ${failed.length} 个。${failed.slice(0, 2).join('；')}`
        )
      } else {
        setResultType('success')

        setResultMessage(`班级签到完成，成功 ${success} 个。`)
      }

      await fetchSigninTasks()

      await fetchSigninHistory()
    } finally {
      setSubmitting(false)
    }
  }, [
    classOptions,
    executeClassSignin,
    fetchSigninHistory,
    fetchSigninTasks,
    form.selectedClassIds,
    form.signType,
    submitting,
  ])

  // Auto-detect: apply the detected task's sign-in type (and matching class
  // selection when available) into the form so the user only sees fields
  // relevant to the activity the teacher actually started.
  const applyDetectedTask = useCallback(
    (task) => {
      if (!task) return
      const detectedType = String(task?.type || 'normal')
      const classKey = String(task?.classSubjectId || task?.classId || '').trim()
      const matchedClass = classKey
        ? classOptions.find((opt) => opt.classId === classKey || opt.id === classKey)
        : null
      setForm((prev) => ({
        ...prev,
        signType: detectedType,
        ...(matchedClass ? { selectedClassIds: [matchedClass.id] } : {}),
      }))
      setResultType('info')
      setResultMessage(
        `已识别为「${detectedType}」类型签到${task?.courseName ? `（${task.courseName}）` : ''}，` +
          `请补全必填字段后点击「立即签到」。`
      )
    },
    [classOptions]
  )

  const applyAndSubmitDetectedTask = useCallback(
    async (task) => {
      if (!task) return
      const detectedType = String(task?.type || 'normal')
      applyDetectedTask(task)
      // Build a class option the same way TasksTab does — every active task on
      // Chaoxing is class-scoped, so we route through executeClassSignin to
      // include classId for correct payload routing.
      const classOption = {
        id: task.courseSelector || task.courseId || task.classId,
        classId: String(task.classId || ''),
        courseId: String(task.rawCourseId || ''),
        courseSelector: String(task.courseSelector || task.courseId || ''),
        name: task.className || task.courseName || '检测到的签到',
      }
      if (classOption.classId) {
        await executeClassSignin(classOption, detectedType)
      } else if (task.courseId) {
        await executeSignin(task.courseId, detectedType)
      }
    },
    [applyDetectedTask, executeClassSignin, executeSignin]
  )

  const verifyAccount = async (event) => {
    event.preventDefault()

    if (submitting) return

    const username = form.username.trim()

    const password = form.password

    if (!username || !password) {
      setResultType('error')

      setResultMessage('请输入账号和密码。')

      return
    }

    setSubmitting(true)

    setResultMessage('')

    try {
      const resp = await requestChaoxingApi('/login', {
        username,

        password,

        use_cookies: false,
      })

      setResultType('success')

      setResultMessage(pickMessage(resp) || '账号验证成功。')

      void fetchCourses()

      void fetchClasses()
    } catch (err) {
      setResultType('error')

      setResultMessage(err.message || '账号验证失败。')
    } finally {
      setSubmitting(false)
    }
  }

  const startSigninTask = async () => {
    if (submitting) return

    const username = form.username.trim()

    const password = form.password

    if (!username || !password) {
      setResultType('error')

      setResultMessage('请输入账号和密码。')

      return
    }

    setSubmitting(true)

    setResultMessage('')

    setLogs([])

    setTaskStatus(null)

    setTaskId('')

    try {
      const selectedCourseOptions = form.selectedCourseIds
        .map((id) => courseOptions.find((course) => course.id === id))
        .filter(Boolean)
      const selectedCourseNames = selectedCourseOptions.map((course) => course.name).filter(Boolean)

      if (
        form.selectedCourseIds.length > 0 &&
        selectedCourseOptions.length !== form.selectedCourseIds.length
      ) {
        throw new Error('选中的课程无效，请重新选择后再试。')
      }

      const payload = {
        username,
        password,
        course_list: selectedCourseOptions.map((course) => course.id),

        speed: 1,

        jobs: 1,

        sign_type: normalizeSignTypeForApi(form.signType),

        notopen_action: 'retry',

        tiku_config: {},

        notification_config: {},

        ocr_config: {},
      }

      const { payload: signPayload, signType } = buildSigninPayload(null, form.signType)

      if (signPayload.latitude !== undefined) payload.latitude = signPayload.latitude

      if (signPayload.longitude !== undefined) payload.longitude = signPayload.longitude

      if (signPayload.address !== undefined) payload.address = signPayload.address

      if (signPayload.altitude !== undefined) payload.altitude = signPayload.altitude

      if (signPayload.qr_code !== undefined) payload.qr_code = signPayload.qr_code

      if (signPayload.sign_code !== undefined) payload.sign_code = signPayload.sign_code

      if (signPayload.gesture !== undefined) payload.gesture = signPayload.gesture

      let resp

      if (form.photoFile && (signType === 'photo' || signType === 'all')) {
        const photoBase64 = await fileToBase64(form.photoFile)

        payload.photo_base64 = photoBase64
      }

      resp = await requestChaoxingApi('/start', payload)

      const nextTaskId = resp?.data?.task_id

      if (!nextTaskId) {
        throw new Error('服务端未返回任务 ID。')
      }

      setResultType('success')

      setResultMessage(`签到任务已启动：${nextTaskId}`)

      setBackgroundTaskHistory((prev) =>
        upsertBackgroundTaskHistory(prev, {
          task_id: nextTaskId,

          status: 'running',

          message: pickMessage(resp) || '签到任务已启动。',

          courseName: selectedCourseNames.join('、') || '后台签到任务',

          created_at: new Date().toISOString(),

          updated_at: new Date().toISOString(),
        })
      )

      await openBackgroundTask(nextTaskId, {
        setResultType,
        setResultMessage,
        setBackgroundTaskHistory,
      })

      void fetchBackgroundTaskHistory()
    } catch (err) {
      setResultType('error')

      setResultMessage(err.message || '启动签到任务失败。')
    } finally {
      setSubmitting(false)
    }
  }

  const startClassSigninTask = async () => {
    if (submitting) return

    const username = form.username.trim()

    const password = form.password

    if (!username || !password) {
      setResultType('error')

      setResultMessage('请输入账号和密码。')

      return
    }

    setSubmitting(true)

    setResultMessage('')

    setLogs([])

    setTaskStatus(null)

    setTaskId('')

    try {
      const selectedClassOptions = form.selectedClassIds
        .map((id) => classOptions.find((subject) => subject.id === id))
        .filter(Boolean)

      if (
        form.selectedClassIds.length > 0 &&
        selectedClassOptions.length !== form.selectedClassIds.length
      ) {
        throw new Error('选中的班级无效，请重新选择后再试。')
      }

      const selectedClassNames = selectedClassOptions.map((subject) => subject.name).filter(Boolean)

      const payload = {
        username,

        password,

        subject_type: 'class',

        class_list: selectedClassOptions.map((subject) => subject.classId).filter(Boolean),

        course_list: selectedClassOptions
          .map((subject) => subject.courseSelector || subject.courseId)
          .filter(Boolean),

        speed: 1,

        jobs: 1,

        sign_type: normalizeSignTypeForApi(form.signType),

        notopen_action: 'retry',

        tiku_config: {},

        notification_config: {},

        ocr_config: {},
      }

      const { payload: signPayload, signType } = buildSigninPayload(null, form.signType)

      if (signPayload.latitude !== undefined) payload.latitude = signPayload.latitude

      if (signPayload.longitude !== undefined) payload.longitude = signPayload.longitude

      if (signPayload.address !== undefined) payload.address = signPayload.address

      if (signPayload.altitude !== undefined) payload.altitude = signPayload.altitude

      if (signPayload.qr_code !== undefined) payload.qr_code = signPayload.qr_code

      if (signPayload.sign_code !== undefined) payload.sign_code = signPayload.sign_code

      if (signPayload.gesture !== undefined) payload.gesture = signPayload.gesture

      if (form.photoFile && (signType === 'photo' || signType === 'all')) {
        payload.photo_base64 = await fileToBase64(form.photoFile)
      }

      const resp = await requestChaoxingApi('/class-start', payload)

      const nextTaskId = resp?.data?.task_id

      if (!nextTaskId) {
        throw new Error('服务端未返回任务 ID。')
      }

      setResultType('success')

      setResultMessage(`班级签到任务已启动：${nextTaskId}`)

      setBackgroundTaskHistory((prev) =>
        upsertBackgroundTaskHistory(prev, {
          task_id: nextTaskId,

          status: 'running',

          message: pickMessage(resp) || '班级签到任务已启动。',

          courseName: selectedClassNames.join('、') || '班级后台签到任务',

          created_at: new Date().toISOString(),

          updated_at: new Date().toISOString(),
        })
      )

      await openBackgroundTask(nextTaskId, {
        setResultType,
        setResultMessage,
        setBackgroundTaskHistory,
      })

      void fetchBackgroundTaskHistory()
    } catch (err) {
      setResultType('error')

      setResultMessage(err.message || '启动班级签到任务失败。')
    } finally {
      setSubmitting(false)
    }
  }

  const taskPretty = useMemo(() => {
    if (!taskStatus) return ''

    try {
      return JSON.stringify(taskStatus, null, 2)
    } catch (_) {
      return String(taskStatus)
    }
  }, [taskStatus])

  // A background task is "running" while we have a task id and its status has
  // not reached a terminal state — used for the cross-tab progress pill so a
  // user who switches tabs still knows something is happening.
  const taskRunning =
    Boolean(taskId) && !['completed', 'error', 'failed', 'cancelled'].includes(taskStatus?.status)

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="overflow-x-hidden">
      <main className="space-y-6">
        <div className={GLASS_CARD_CLASS}>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold text-text">学习通签到</h1>

            {taskRunning && (
              <button
                type="button"
                onClick={() => setActiveTab('signin')}
                className="inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/20"
                title="查看后台任务进度"
              >
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/60" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
                </span>
                后台任务进行中
              </button>
            )}
          </div>

          <p className="mt-1 text-sm text-text/70">完整签到功能与实时监控。</p>
        </div>

        <StatsCards todayStats={todayStats} />

        <div className={GLASS_CARD_CLASS}>
          <div className="flex flex-wrap gap-2 border-b border-border/20 pb-4">
            <button
              onClick={() => setActiveTab('signin')}
              className={`min-h-[44px] rounded-xl px-4 py-2 font-medium transition-all duration-200 cursor-pointer ${
                activeTab === 'signin'
                  ? 'bg-primary text-white'
                  : 'bg-surface/60 text-text hover:bg-surface/80'
              }`}
            >
              签到
            </button>

            <button
              onClick={() => setActiveTab('tasks')}
              className={`min-h-[44px] rounded-xl px-4 py-2 font-medium transition-all duration-200 cursor-pointer ${
                activeTab === 'tasks'
                  ? 'bg-primary text-white'
                  : 'bg-surface/60 text-text hover:bg-surface/80'
              }`}
            >
              任务
            </button>

            <button
              onClick={() => setActiveTab('history')}
              className={`min-h-[44px] rounded-xl px-4 py-2 font-medium transition-all duration-200 cursor-pointer ${
                activeTab === 'history'
                  ? 'bg-primary text-white'
                  : 'bg-surface/60 text-text hover:bg-surface/80'
              }`}
            >
              历史
            </button>

            <button
              onClick={() => setActiveTab('config')}
              className={`min-h-[44px] rounded-xl px-4 py-2 font-medium transition-all duration-200 cursor-pointer ${
                activeTab === 'config'
                  ? 'bg-primary text-white'
                  : 'bg-surface/60 text-text hover:bg-surface/80'
              }`}
            >
              设置
            </button>
          </div>

          {activeTab === 'signin' && (
            <div className="mt-6 space-y-4">
              <AutoSigninBanner
                signinTasks={signinTasks}
                form={form}
                submitting={submitting}
                onApplyTask={applyDetectedTask}
                onApplyAndSubmit={applyAndSubmitDetectedTask}
                onRefresh={fetchSigninTasks}
              />

              <form className="grid grid-cols-1 gap-4 md:grid-cols-2" onSubmit={verifyAccount}>
                <Input
                  id="cx-username"
                  label="账号 / 手机号"
                  type="text"
                  name="cx-username"
                  autoComplete="username"
                  value={form.username}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, username: event.target.value }))
                  }
                  required
                />

                <Input
                  id="cx-password"
                  label="密码"
                  type="password"
                  name="cx-password"
                  autoComplete="current-password"
                  value={form.password}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, password: event.target.value }))
                  }
                  required
                />

                <div className="md:col-span-2">
                  <Select
                    id="cx-signtype"
                    label="签到类型"
                    value={form.signType}
                    onChange={(event) =>
                      setForm((prev) => ({ ...prev, signType: event.target.value }))
                    }
                  >
                    <option value="all">通用模式（自动匹配老师发起的类型）</option>
                    <option value="normal">普通签到</option>
                    <option value="photo">拍照签到</option>
                    <option value="location">位置签到</option>
                    <option value="qrcode">二维码签到</option>
                    <option value="gesture">手势签到</option>
                    <option value="code">签到码签到</option>
                  </Select>
                </div>

                <div className="md:col-span-2">
                  <MultiSelect
                    label="课程选择（可选，不选即全部课程）"
                    options={courseOptions}
                    selectedIds={form.selectedCourseIds}
                    onChange={(ids) => setForm((prev) => ({ ...prev, selectedCourseIds: ids }))}
                    emptyHint="暂无课程，请先验证账号后刷新课程"
                    headerAction={
                      <Button
                        type="button"
                        variant="secondary"
                        aria-label="刷新课程列表"
                        title="刷新课程列表"
                        className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200"
                        onClick={fetchCourses}
                      >
                        <RefreshCw className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    }
                  />
                </div>

                <div className="md:col-span-2">
                  <MultiSelect
                    label="班级选择（班级签到入口）"
                    options={classOptions}
                    selectedIds={form.selectedClassIds}
                    onChange={(ids) => setForm((prev) => ({ ...prev, selectedClassIds: ids }))}
                    emptyHint="暂无班级，请先验证账号后刷新班级"
                    headerAction={
                      <Button
                        type="button"
                        variant="secondary"
                        aria-label="刷新班级列表"
                        title="刷新班级列表"
                        className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200"
                        onClick={fetchClasses}
                      >
                        <RefreshCw className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    }
                  />
                </div>

                {form.signType === 'all' && (
                  <div className="md:col-span-2">
                    <button
                      type="button"
                      onClick={() => setAdvancedOpen((open) => !open)}
                      aria-expanded={advancedOpen}
                      className="flex min-h-[44px] w-full items-center justify-between rounded-xl border border-border/60 bg-surface/60 px-4 py-2 text-sm text-text/80 transition-colors hover:bg-surface-hover"
                    >
                      <span>补充签到参数（可选）— 通用模式会自动匹配老师发起的类型，如需可手动预填照片 / 位置 / 二维码等</span>
                      <ChevronDown
                        className={`h-4 w-4 shrink-0 transition-transform ${advancedOpen ? 'rotate-180' : ''}`}
                        aria-hidden="true"
                      />
                    </button>
                  </div>
                )}

                {(form.signType === 'photo' || (form.signType === 'all' && advancedOpen)) && (
                  <div className="md:col-span-2">
                    <label htmlFor="cx-photo" className="mb-2 block text-sm font-medium text-text">
                      签到照片（自拍/拍照）
                    </label>

                    <div className="flex items-center gap-3">
                      <label
                        htmlFor="cx-photo"
                        className="flex min-h-[44px] cursor-pointer items-center gap-2 rounded-xl border border-border/30 bg-surface/60 px-4 py-2 text-sm text-text backdrop-blur-sm transition-all duration-200 hover:border-primary/50 hover:bg-surface/80"
                      >
                        <Camera className="h-4 w-4" />
                        选择照片
                      </label>

                      <input
                        id="cx-photo"
                        type="file"
                        accept="image/*"
                        className="hidden"
                        onChange={(event) =>
                          setForm((prev) => ({
                            ...prev,
                            photoFile: event.target.files?.[0] || null,
                          }))
                        }
                      />

                      <p className="text-xs text-text/70">
                        {form.photoFile
                          ? `已选择：${form.photoFile.name}（${(form.photoFile.size / 1024).toFixed(0)} KB）`
                          : '请上传自拍照片，支持 JPG/PNG 格式。'}
                      </p>
                    </div>

                    {form.photoFile && (
                      <div className="mt-3">
                        <img
                          src={URL.createObjectURL(form.photoFile)}
                          alt="预览"
                          className="h-32 w-32 rounded-xl border border-border/30 object-cover"
                        />
                      </div>
                    )}
                  </div>
                )}

                {(form.signType === 'location' ||
                  form.signType === 'qrcode' ||
                  form.signType === 'gesture' ||
                  (form.signType === 'all' && advancedOpen)) && (
                  <div className="space-y-3 md:col-span-2">
                    {/* Primary path: one tap to fill coordinates. */}
                    <div className="flex flex-wrap gap-3">
                      <Button
                        type="button"
                        variant="secondary"
                        className="inline-flex min-h-[44px] items-center gap-2 cursor-pointer transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-60"
                        onClick={useCurrentLocation}
                        disabled={geocodeLoading}
                      >
                        <MapPin className="h-4 w-4" aria-hidden="true" />
                        使用当前位置
                      </Button>

                      <Button
                        type="button"
                        variant="secondary"
                        className="inline-flex min-h-[44px] items-center gap-2 cursor-pointer transition-all duration-200"
                        onClick={() => setIsMapPickerOpen(true)}
                      >
                        <Map className="h-4 w-4" aria-hidden="true" />
                        在地图上选点
                      </Button>
                    </div>

                    {/* Or look up by place name. */}
                    <Input
                      id="cx-address"
                      label="地址 / 地点名称"
                      type="text"
                      value={form.address}
                      onChange={(e) => {
                        latestAddressRef.current = e.target.value
                        setForm((prev) => ({ ...prev, address: e.target.value }))
                      }}
                      placeholder="例如：北京市朝阳区"
                    />

                    <div className="flex flex-wrap items-center gap-3">
                      <Button
                        type="button"
                        variant="secondary"
                        className="min-h-[44px] cursor-pointer transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-60"
                        onClick={resolveLocationCoordinates}
                        disabled={geocodeLoading}
                      >
                        {geocodeLoading ? '解析中...' : '解析坐标'}
                      </Button>

                      <Button
                        type="button"
                        variant="secondary"
                        className="min-h-[44px] cursor-pointer transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-60"
                        onClick={searchLocationCandidates}
                        disabled={placeSearchLoading}
                      >
                        {placeSearchLoading ? '搜索中...' : '搜索地点'}
                      </Button>

                      <p
                        className={`text-xs ${
                          geocodeStatus === 'error'
                            ? 'text-danger'
                            : geocodeStatus === 'success'
                              ? 'text-success'
                              : 'text-text/70'
                        }`}
                      >
                        {geocodeMessage || '可使用当前位置、地图选点，或输入地点名称后解析坐标。'}
                      </p>
                    </div>

                    {placeSearchMessage ? (
                      <p className="text-xs text-text/70">{placeSearchMessage}</p>
                    ) : null}

                    {placeSearchResults.length > 0 ? (
                      <div className="space-y-2 rounded-xl border border-border/40 bg-surface/50 p-3 backdrop-blur-sm">
                        {placeSearchResults.map((candidate) => (
                          <button
                            key={candidate.id}
                            type="button"
                            data-place-result-id={candidate.id}
                            className="w-full rounded-xl border border-transparent bg-surface/70 px-4 py-3 text-left transition-all duration-200 hover:border-primary/40 hover:bg-surface"
                            onClick={() => choosePlaceSearchResult(candidate)}
                          >
                            <span className="block text-sm font-medium text-text">
                              {candidate.name || candidate.address}
                            </span>

                            <span className="mt-1 block text-xs text-text/70">
                              {candidate.address}
                            </span>
                          </button>
                        ))}
                      </div>
                    ) : null}

                    {/* Manual override — pre-filled by the actions above; rarely needed. */}
                    <details className="rounded-xl border border-border/60 bg-surface/40 p-3">
                      <summary className="cursor-pointer text-sm text-text/80">
                        手动输入坐标（高级）— 上方操作会自动填好，通常无需修改
                      </summary>
                      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
                        <Input
                          id="cx-latitude"
                          label="纬度"
                          type="text"
                          value={form.latitude}
                          onChange={(e) =>
                            setForm((prev) => ({ ...prev, latitude: e.target.value }))
                          }
                          placeholder="e.g. 39.9042"
                        />

                        <Input
                          id="cx-longitude"
                          label="经度"
                          type="text"
                          value={form.longitude}
                          onChange={(e) =>
                            setForm((prev) => ({ ...prev, longitude: e.target.value }))
                          }
                          placeholder="e.g. 116.4074"
                        />

                        <Input
                          id="cx-altitude"
                          label="海拔（米）"
                          type="number"
                          step="0.1"
                          value={form.altitude}
                          onChange={(e) =>
                            setForm((prev) => ({ ...prev, altitude: e.target.value }))
                          }
                          placeholder="留空则使用默认 100"
                        />
                      </div>
                      <p className="mt-2 text-xs text-text-muted">坐标使用百度 BD-09 坐标系。</p>
                    </details>
                  </div>
                )}

                {(form.signType === 'qrcode' || (form.signType === 'all' && advancedOpen)) && (
                  <div className="md:col-span-2 space-y-4">
                    <div>
                      <label
                        htmlFor="cx-qrcode-file"
                        className="mb-2 block text-sm font-medium text-text"
                      >
                        上传二维码图片
                      </label>

                      <div className="flex items-center gap-3">
                        <label
                          htmlFor="cx-qrcode-file"
                          className="flex min-h-[44px] cursor-pointer items-center gap-2 rounded-xl border border-border/30 bg-surface/60 px-4 py-2 text-sm text-text backdrop-blur-sm transition-all duration-200 hover:border-primary/50 hover:bg-surface/80"
                        >
                          <Upload className="h-4 w-4" />
                          选择二维码图片
                        </label>

                        <input
                          id="cx-qrcode-file"
                          type="file"
                          accept="image/*"
                          className="hidden"
                          onChange={(e) => {
                            const file = e.target.files?.[0]

                            if (file) handleQrCodeFileUpload(file)
                          }}
                        />

                        <p
                          className={`text-xs ${form.qrDecodeStatus.includes('成功') ? 'text-success' : form.qrDecodeStatus.includes('失败') || form.qrDecodeStatus.includes('无法') ? 'text-danger' : 'text-text/70'}`}
                        >
                          {form.qrDecodeStatus ||
                            (form.qrCodeFile
                              ? `已选择：${form.qrCodeFile.name}`
                              : '支持 JPG/PNG 格式的二维码截图')}
                        </p>
                      </div>
                    </div>

                    <Input
                      id="cx-qrcode"
                      label="二维码内容（上传图片后自动填充，也可手动输入）"
                      type="text"
                      value={form.qrCode}
                      onChange={(e) => setForm((prev) => ({ ...prev, qrCode: e.target.value }))}
                      placeholder="上传二维码图片后自动解析，或手动粘贴二维码链接"
                    />

                    <p className="text-xs text-text/70">
                      二维码签到可附带经纬度、地址和海拔参数以提高成功率。
                    </p>
                  </div>
                )}

                {(form.signType === 'gesture' || (form.signType === 'all' && advancedOpen)) && (
                  <div className="md:col-span-2">
                    <Input
                      id="cx-gesture"
                      label="手势编码"
                      type="text"
                      value={form.gesturePattern}
                      onChange={(e) =>
                        setForm((prev) => ({ ...prev, gesturePattern: e.target.value }))
                      }
                      placeholder="请输入老师发布的手势编码"
                    />

                    <p className="mt-2 text-xs text-text/70">
                      手势签到可附带位置参数，填写下方地址信息以提高成功率。
                    </p>
                  </div>
                )}

                {(form.signType === 'code' || (form.signType === 'all' && advancedOpen)) && (
                  <div className="md:col-span-2">
                    <Input
                      id="cx-sign-code"
                      label="签到码"
                      type="text"
                      value={form.signCode}
                      onChange={(e) => setForm((prev) => ({ ...prev, signCode: e.target.value }))}
                      placeholder="请输入老师发布的签到码"
                    />
                  </div>
                )}

                <div className="md:col-span-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
                  <Button
                    type="submit"
                    variant="secondary"
                    className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed"
                    disabled={submitting}
                  >
                    {submitting ? '验证中...' : '验证账号'}
                  </Button>

                  <Button
                    type="button"
                    className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed"
                    onClick={() => executeSignin()}
                    disabled={submitting}
                  >
                    {submitting ? '签到中...' : '课程签到'}
                  </Button>

                  <Button
                    type="button"
                    variant="cta"
                    className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed"
                    onClick={startSigninTask}
                    disabled={submitting}
                  >
                    {submitting ? '处理中...' : '课程任务'}
                  </Button>

                  <Button
                    type="button"
                    className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed"
                    onClick={executeSelectedClassSignin}
                    disabled={submitting || classOptions.length === 0}
                  >
                    {submitting ? '签到中...' : '班级签到'}
                  </Button>

                  <Button
                    type="button"
                    variant="cta"
                    className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed"
                    onClick={startClassSigninTask}
                    disabled={submitting || classOptions.length === 0}
                  >
                    {submitting ? '处理中...' : '班级任务'}
                  </Button>

                  <Button
                    type="button"
                    variant="secondary"
                    className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200"
                    onClick={() => navigate('/chaoxing-fanya')}
                  >
                    打开泛雅页面
                  </Button>
                </div>
              </form>

              {(taskId || taskStatus || logs.length > 0) && (
                <div className={GLASS_PANEL_CLASS}>
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                    <h3 className="text-base font-semibold text-text">任务状态</h3>

                    <Button
                      type="button"
                      variant="secondary"
                      className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed"
                      onClick={() =>
                        refreshTaskStatus(taskId, {
                          setResultType,
                          setResultMessage,
                          setBackgroundTaskHistory,
                        })
                      }
                      disabled={!taskId || statusLoading}
                    >
                      {statusLoading ? (
                        <span className="inline-flex items-center gap-2">
                          <Loader2 className="h-4 w-4 animate-spin" />
                          刷新中...
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-2">
                          <RefreshCw className="h-4 w-4" />
                          刷新状态
                        </span>
                      )}
                    </Button>
                  </div>

                  {taskId && (
                    <p className="mb-2 text-sm text-text/80">
                      任务 ID：<span className="font-mono">{taskId}</span>
                    </p>
                  )}

                  {taskStatus && (
                    <pre className="mb-3 max-h-48 overflow-auto rounded-xl border border-border/20 bg-slate-900/90 p-3 text-xs text-slate-100">
                      {taskPretty}
                    </pre>
                  )}

                  <div>
                    <p className="mb-2 text-sm font-medium text-text">实时日志</p>

                    <div
                      ref={logContainerRef}
                      role="log"
                      aria-live="polite"
                      aria-label="实时日志"
                      className="max-h-56 space-y-1 overflow-y-auto rounded-xl border border-border/20 bg-slate-900/90 p-3 font-mono text-xs text-slate-100"
                    >
                      {logs.length === 0 ? (
                        <p className="text-slate-300">暂无日志</p>
                      ) : (
                        logs.map((log, index) => {
                          const message =
                            typeof log === 'string' ? log : log?.message || safeStringify(log)

                          const timestamp =
                            typeof log === 'object' && log?.timestamp ? String(log.timestamp) : ''

                          return (
                            <p key={`${timestamp}-${index}`} className="break-all">
                              {timestamp ? `[${timestamp}] ` : ''}
                              {message}
                            </p>
                          )
                        })
                      )}
                    </div>
                  </div>
                </div>
              )}

              <div className={GLASS_PANEL_CLASS}>
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <h3 className="text-base font-semibold text-text">后台任务历史</h3>

                  <Button
                    type="button"
                    variant="secondary"
                    aria-label="刷新后台任务历史"
                    title="刷新后台任务历史"
                    className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200"
                    onClick={() => {
                      void fetchBackgroundTaskHistory()
                    }}
                  >
                    <RefreshCw className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </div>

                {backgroundTaskHistory.length === 0 ? (
                  <p className="text-sm text-text/70">暂无后台任务历史</p>
                ) : (
                  <div className="max-h-64 space-y-2 overflow-y-auto">
                    {backgroundTaskHistory.map((task) => {
                      const isActive = task.taskId === taskId

                      const statusClassName =
                        task.status === 'completed'
                          ? 'border-success/30 bg-success-surface text-success'
                          : task.status === 'error'
                            ? 'border-danger/30 bg-danger-surface text-danger'
                            : 'border-amber-300 bg-amber-50 text-amber-700'

                      return (
                        <button
                          key={task.taskId}
                          type="button"
                          className={`w-full min-h-[44px] rounded-xl border px-3 py-3 text-left transition-all duration-200 cursor-pointer ${isActive ? 'border-primary/50 bg-primary/10' : 'border-border/30 bg-surface/70 hover:border-primary/40'}`}
                          onClick={() => {
                            void openBackgroundTask(task.taskId, {
                              setResultType,
                              setResultMessage,
                              setBackgroundTaskHistory,
                            })
                          }}
                        >
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div className="min-w-0 flex-1">
                              <p className="font-medium text-text">
                                {task.courseName || '后台签到任务'}
                              </p>

                              <p className="mt-1 break-all font-mono text-xs text-text/70">
                                任务 ID：{task.taskId}
                              </p>
                            </div>

                            <span
                              className={`rounded-full border px-2 py-1 text-xs font-medium ${statusClassName}`}
                            >
                              {task.status || 'unknown'}
                            </span>
                          </div>

                          <p className="mt-2 text-sm text-text/80">{task.message || '暂无消息'}</p>

                          <p className="mt-1 text-xs text-text/60">
                            更新时间：
                            {parseTaskTimestamp(task.updatedAt || task.createdAt) > 0
                              ? new Date(task.updatedAt || task.createdAt).toLocaleString()
                              : '--'}
                          </p>
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === 'tasks' && (
            <TasksTab
              signinTasks={signinTasks}
              fetchSigninTasks={fetchSigninTasks}
              openBackgroundTask={(tid) =>
                openBackgroundTask(tid, {
                  setResultType,
                  setResultMessage,
                  setBackgroundTaskHistory,
                })
              }
              executeSignin={executeSignin}
              executeClassSignin={executeClassSignin}
            />
          )}

          {activeTab === 'history' && (
            <HistoryTab signinHistory={signinHistory} fetchSigninHistory={fetchSigninHistory} />
          )}

          {activeTab === 'config' && (
            <ConfigTab
              autoSignin={autoSignin}
              setAutoSignin={setAutoSignin}
              autoSignFilter={autoSignFilter}
              setAutoSignFilter={setAutoSignFilter}
              checkInterval={checkInterval}
              setCheckInterval={setCheckInterval}
              nextCheckCountdown={nextCheckCountdown}
            />
          )}
        </div>
      </main>

      {isMapPickerOpen && (
        <Suspense fallback={null}>
          <BaiduMapPickerModal
            open={isMapPickerOpen}
            initialLocation={{
              latitude: form.latitude,
              longitude: form.longitude,
              address: form.address,
            }}
            onClose={() => setIsMapPickerOpen(false)}
            onConfirm={(location) => {
              applyResolvedLocation(location)
              setGeocodeStatus('success')
              setGeocodeMessage(`已选点：${location.latitude}, ${location.longitude}`)
              setIsMapPickerOpen(false)
            }}
          />
        </Suspense>
      )}
    </div>
  )
}
