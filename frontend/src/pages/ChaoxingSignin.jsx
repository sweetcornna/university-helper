import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { BookMarked, Camera, ChevronDown, Map, MapPin, MessagesSquare, RefreshCw, Search, Upload, Users } from 'lucide-react'

import { getToken, removeToken } from '../utils/auth'
import { APP_JWT_401_PATTERN } from '../utils/api'

import { AccountChip, Button, Input, MultiSelect, PageHeader, Select, StateNotice, StatusBadge, useRuntimeProfile, useToast } from '../components'
import WorkspaceTabs from '../components/WorkspaceTabs'
import useWorkspaceTab from '../components/useWorkspaceTab'

// Tabs follow the student's order of work: verify the account, choose a
// course or class and sign in, review detected activities, then background
// tasks and records. The default stays on 手动签到, which asks for the account
// first when it has not been verified.
const CHAOXING_TABS = [
  { id: 'account', label: '账号' },
  { id: 'signin', label: '手动签到' },
  { id: 'tasks', label: '待处理签到' },
  { id: 'monitor', label: '自动监控' },
  { id: 'history', label: '签到记录' },
]

const SIGNIN_SCOPES = [
  { id: 'course', label: '课程', icon: BookMarked },
  { id: 'class', label: '班级', icon: Users },
  { id: 'chat', label: '群聊', icon: MessagesSquare },
]

const RESULT_NOTICE = {
  done: { kind: 'done', title: '已完成' },
  error: { kind: 'error', title: '未成功' },
  partial: { kind: 'error', title: '未全部成功' },
  guided: { kind: 'warning', title: '需在学习通完成' },
  unconfirmed: { kind: 'unknown', title: '结果未确认' },
  info: { kind: 'info', title: '提示' },
}

const SCOPE_LABEL = { course: '课程签到', class: '班级签到' }

// One summary for a multi-course/class run. Counts stay separate, and the
// detail line comes from the item that most needs attention (unconfirmed,
// then 学习通 hand-off, then failure) so it is never buried under successes.
const formatBatchOutcome = (label, unit, results) => {
  const { kind, counts, lead } = summarizeBatchResults(results)
  const parts = [`成功 ${counts.done} ${unit}`]
  if (counts.unconfirmed) parts.push(`结果未确认 ${counts.unconfirmed} ${unit}`)
  if (counts.guided) parts.push(`需在学习通完成 ${counts.guided} ${unit}`)
  if (counts.error + counts.info) parts.push(`失败 ${counts.error + counts.info} ${unit}`)
  const detail = lead && lead.kind !== 'done' ? `${lead.name ? `${lead.name}：` : ''}${lead.message}` : ''
  const toastType = counts.done === results.length ? 'success' : counts.done > 0 ? 'info' : 'error'
  return {
    kind: kind === 'error' && counts.done > 0 ? 'partial' : kind,
    toastType,
    message: `${label}签到完成，${parts.join('，')}。${detail}`,
  }
}

// Lazy-load the map picker (pulls in ~150KB of leaflet) only when the user
// opens it, so the initial signin page stays light on mobile.
const BaiduMapPickerModal = lazy(() => import('../components/BaiduMapPickerModal'))

import {
  CHAOXING_API_BASE,
  GLASS_CARD_CLASS,
  getSignTypeLabel,
  parsePayload,
  pickMessage,
  normalizeSignTypeForApi,
  shouldUseLocationParams,
  fileToBase64,
  validatePhotoFile,
  decodeQrCodeFromFile,
  normalizeBackgroundTaskHistory,
  upsertBackgroundTaskHistory,
  isBackgroundTaskRunning,
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
import useChatSignin from './chaoxing-signin/hooks/useChatSignin'
import ChatSigninSection from './chaoxing-signin/components/ChatSigninSection'
import { fetchWithTimeout } from './chaoxing-signin/request'

import StatsCards from './chaoxing-signin/components/StatsCards'
import BackgroundTaskDetail from './chaoxing-signin/components/BackgroundTaskDetail'
import {
  backgroundTaskBadge,
  classifyResult,
  isBackgroundTaskActive,
  summarizeBatchResults,
} from './chaoxing-signin/taskPresentation'
import TasksTab from './chaoxing-signin/components/TasksTab'
import HistoryTab from './chaoxing-signin/components/HistoryTab'
import ConfigTab from './chaoxing-signin/components/ConfigTab'
import AutoSigninBanner from './chaoxing-signin/components/AutoSigninBanner'

import { readLastUsername, saveLastUsername } from '../utils/chaoxingCreds'

export default function ChaoxingSignin() {
  const navigate = useNavigate()
  const { isLocal } = useRuntimeProfile()

  const ensureAccessTokenRef = useRef(null)

  const redirectToLoginRef = useRef(null)

  const redirectingRef = useRef(false)

  const setTodayStatsRef = useRef(null)

  const toast = useToast()

  const [submitting, setSubmitting] = useState(false)
  const [accountReady, setAccountReady] = useState(false)
  const accountGenerationRef = useRef(0)
  const coursesRequestRef = useRef(0)
  const classesRequestRef = useRef(0)

  const [resultMessage, setResultMessage] = useState('')

  const [resultType, setResultType] = useState('info')

  // The most recent manual sign-in result stays on the form after its toast
  // fades. Only the manual operation that produced it writes it, and it is
  // shown only for the account it was made with; account checks, auto sign-in,
  // refreshes and background messages stay in the toast.
  const [lastResult, setLastResult] = useState(null)
  const manualOperationRef = useRef(0)
  const backgroundCreateRef = useRef(false)

  const historyDetailRef = useRef(null)

  const [activeTab, setActiveTab] = useWorkspaceTab(CHAOXING_TABS, 'signin', { config: 'monitor' })

  // In 通用模式(all) the type-specific fields are optional (the backend
  // auto-matches the teacher's type), so they stay collapsed behind this
  // disclosure instead of flooding the form with all six groups at once.
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const [courses, setCourses] = useState([])

  const [classSubjects, setClassSubjects] = useState([])

  const [signinTasks, setSigninTasks] = useState([])
  const [signinTasksLoading, setSigninTasksLoading] = useState(false)
  const [signinTasksError, setSigninTasksError] = useState('')
  const signinTasksRequestRef = useRef(0)
  const [signinTarget, setSigninTarget] = useState('course')

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

  const photoPreviewUrl = useMemo(
    () => (form.photoFile ? URL.createObjectURL(form.photoFile) : ''),
    [form.photoFile],
  )

  useEffect(() => () => {
    if (photoPreviewUrl) URL.revokeObjectURL(photoPreviewUrl)
  }, [photoPreviewUrl])

  const ensureAccessToken = useCallback(() => {
    return isLocal ? null : getToken() || null
  }, [isLocal])

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

      if (!isLocal && !token) {
        redirectToLoginRef.current('登录态失效，请重新登录。')
      }

      const hasBody = body !== undefined && body !== null

      const isFormData = body instanceof FormData

      const method = options.method || (hasBody ? 'POST' : 'GET')

      const headers = {
        ...(options.headers || {}),
        ...(!isLocal && token ? { Authorization: `Bearer ${token}` } : {}),
      }

      if (hasBody && !isFormData && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json'
      }

      const response = await fetchWithTimeout(`${CHAOXING_API_BASE}${path}`, {
        ...options,

        method,

        headers,

        body: hasBody ? (isFormData ? body : JSON.stringify(body)) : undefined,
      })

      const payload = await parsePayload(response)

      const message = pickMessage(payload)

      const code = payload?.code || payload?.error_code

      // A platform 401 (e.g. 学习通未登录) needs platform login and must not
      // discard the app's own session. Share the app-auth message contract.
      const isAuthFailure =
        code === 'AUTH_TOKEN_EXPIRED' ||
        code === 'AUTH_INVALID_TOKEN' ||
        ((response.status === 401 || (response.status === 200 && payload?.status === false)) &&
          APP_JWT_401_PATTERN.test(String(message || '')))

      if (isAuthFailure && !isLocal) {
        redirectToLogin('登录已过期，请重新登录。')
      }

      if (!response.ok) {
        throw new Error(message || `请求失败（${response.status}）`)
      }

      if (payload?.status === false) {
        const error = new Error(message || '请求失败')
        error.payload = payload
        throw error
      }

      return payload
    },

    [isLocal, redirectToLogin]
  )

  // ── Hooks ──────────────────────────────────────────────────────────────────

  const backgroundTasks = useBackgroundTasks(requestChaoxingApi)
  const {
    taskId,
    taskStatus,
    logs,
    statusLoading,
    refreshTaskStatus,
    openBackgroundTask,
    stopPolling,
  } = backgroundTasks

  const locationServices = useLocationServices(requestChaoxingApi, setForm)
  const {
    geocodeLoading,
    geocodeMessage,
    geocodeStatus,
    setGeocodeStatus,
    setGeocodeMessage,
    handleAddressChange,
    placeSearchLoading,
    placeSearchResults,
    placeSearchMessage,
    isMapPickerOpen,
    setIsMapPickerOpen,
    applyUserLocationIntent,
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

  // A manual operation captures its scope, account and account generation at
  // launch. Its result is kept only if no newer manual operation started and
  // the account was not re-verified in the meantime.
  const beginManualOperation = useCallback((scope) => {
    const id = manualOperationRef.current + 1
    manualOperationRef.current = id
    return { id, scope, account: form.username.trim(), generation: accountGenerationRef.current }
  }, [form.username])

  const recordManualResult = useCallback((operation, kind, message) => {
    if (!operation || operation.id !== manualOperationRef.current) return
    if (operation.generation !== accountGenerationRef.current) return
    setLastResult({ kind, message, scope: operation.scope, account: operation.account, at: new Date() })
  }, [])

  // Remember the account for next visit (username only).
  useEffect(() => {
    saveLastUsername(form.username)
  }, [form.username])

  // ── Callbacks that depend on requestChaoxingApi ────────────────────────────

  const fetchCourses = useCallback(async () => {
    const generation = accountGenerationRef.current
    const requestId = ++coursesRequestRef.current
    try {
      const resp = await requestChaoxingApi('/courses')
      if (generation !== accountGenerationRef.current || requestId !== coursesRequestRef.current) return
      setCourses(Array.isArray(resp?.data) ? resp.data : [])
    } catch (err) {
      if (!redirectingRef.current && generation === accountGenerationRef.current) {
        setResultType('error')
        setResultMessage(err.message || '获取课程失败，请重试。')
      }
    }
  }, [requestChaoxingApi])

  const fetchClasses = useCallback(async () => {
    const generation = accountGenerationRef.current
    const requestId = ++classesRequestRef.current
    try {
      const resp = await requestChaoxingApi('/classes')
      if (generation !== accountGenerationRef.current || requestId !== classesRequestRef.current) return
      setClassSubjects(resp?.data || resp?.classes || [])
    } catch (err) {
      if (!redirectingRef.current && generation === accountGenerationRef.current) {
        setResultType('error')
        setResultMessage(err.message || '获取班级失败，请重试。')
      }
    }
  }, [requestChaoxingApi])

  const fetchSigninTasks = useCallback(async () => {
    const generation = accountGenerationRef.current
    const requestId = ++signinTasksRequestRef.current
    setSigninTasksLoading(true)
    setSigninTasksError('')
    try {
      const resp = await requestChaoxingApi('/tasks')
      if (generation !== accountGenerationRef.current || requestId !== signinTasksRequestRef.current) return
      setSigninTasks(Array.isArray(resp?.data) ? resp.data : [])
    } catch (err) {
      if (!redirectingRef.current && generation === accountGenerationRef.current && requestId === signinTasksRequestRef.current) {
        setSigninTasksError(err.message || '签到检测失败，请重试。')
      }
    } finally {
      if (requestId === signinTasksRequestRef.current) setSigninTasksLoading(false)
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

  const chatSignin = useChatSignin({
    requestChaoxingApi,
    username: form.username,
    password: form.password,
    location: { latitude: form.latitude, longitude: form.longitude, address: form.address },
    accountGenerationRef,
    onSuccess: fetchSigninHistory,
  })

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
      const operation = silent ? null : beginManualOperation('course')

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

          recordManualResult(operation, classifyResult('success', message), message)
        }

        await fetchSigninHistory()

        return { status: true, message }
      } catch (err) {
        const message = err.message || '签到失败。'

        if (!silent) {
          setResultType('error')

          setResultMessage(message)

          recordManualResult(operation, classifyResult('error', message), message)
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
      beginManualOperation,
      buildSigninPayload,
      fetchSigninHistory,
      form.password,
      form.username,
      recordManualResult,
      requestChaoxingApi,
    ]
  )

  // ── Auto-signin hook (depends on executeSignin) ────────────────────────────

  const autoSigninHook = useAutoSignin(form, executeSignin, requestChaoxingApi, {
    setResultType,
    setResultMessage,
    setSigninTasks,
    redirectingRef,
    paused: !accountReady,
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

  const qrDecodeGenerationRef = useRef(0)

  useEffect(
    () => () => {
      qrDecodeGenerationRef.current += 1
    },
    []
  )

  const handleQrCodeFileUpload = useCallback(async (file) => {
    if (!file) return

    const requestId = qrDecodeGenerationRef.current + 1
    qrDecodeGenerationRef.current = requestId

    setForm((prev) => ({ ...prev, qrCodeFile: file, qrDecodeStatus: '解码中...' }))
    try {
      const decoded = await decodeQrCodeFromFile(file)
      if (qrDecodeGenerationRef.current !== requestId) return
      setForm((prev) => ({ ...prev, qrCode: decoded, qrDecodeStatus: `解码成功` }))
    } catch (err) {
      if (qrDecodeGenerationRef.current !== requestId) return
      setForm((prev) => ({ ...prev, qrDecodeStatus: err.message }))
    }
  }, [])

  // ── Bootstrap effect ───────────────────────────────────────────────────────
  // Route guarding lives in App.jsx (PrivateRoute). Only app-scoped data loads
  // here: courses, classes and sign-in detection need a Chaoxing session, which
  // the backend only holds after this page verifies the account (every sign
  // call re-logs in with the password anyway), so they run from verifyAccount
  // or an explicit refresh — never on load, where they would only fail.

  useEffect(() => {
    redirectingRef.current = false

    let cancelled = false

    const bootstrap = async () => {
      const token = ensureAccessToken()

      if (cancelled) return

      if (!isLocal && !token) {
        navigate('/login', { replace: true })

        return
      }

      const [, backgroundTasksResult] = await Promise.allSettled([
        fetchSigninHistory(),

        fetchBackgroundTaskHistory(),
      ])

      if (cancelled) return

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
    isLocal,
    navigate,
    stopPolling,
    stopAutoCheck,
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
      const operation = silent ? null : beginManualOperation('class')

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

          recordManualResult(operation, classifyResult('success', message), message)
        }

        await fetchSigninHistory()

        return { status: true, message }
      } catch (err) {
        const message = err.message || '班级签到失败。'

        if (!silent) {
          setResultType('error')

          setResultMessage(message)

          recordManualResult(operation, classifyResult('error', message), message)
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
      beginManualOperation,
      buildSigninPayload,
      fetchSigninHistory,
      form.password,
      form.username,
      recordManualResult,
      requestChaoxingApi,
    ]
  )

  const executeSelectedClassSignin = useCallback(async () => {
    if (submitting) return
    const operation = beginManualOperation('class')

    const rejectSelection = (message) => {
      setResultType('error')

      setResultMessage(message)

      recordManualResult(operation, 'error', message)
    }

    const selectedClassOptions = form.selectedClassIds
      .map((id) => classOptions.find((subject) => subject.id === id))
      .filter(Boolean)

    if (selectedClassOptions.length === 0) {
      rejectSelection('请选择班级后再执行班级签到。')

      return
    }

    if (selectedClassOptions.length !== form.selectedClassIds.length) {
      rejectSelection('选中的班级无效，请重新选择后再试。')

      return
    }

    setSubmitting(true)

    setResultMessage('')

    try {
      const results = []

      for (const classOption of selectedClassOptions) {
        const result = await executeClassSignin(classOption, form.signType, { silent: true })

        results.push({ ...result, name: classOption.name })
      }

      const outcome = formatBatchOutcome('班级', '个', results)

      setResultType(outcome.toastType)

      setResultMessage(outcome.message)

      recordManualResult(operation, outcome.kind, outcome.message)

      await fetchSigninTasks()

      await fetchSigninHistory()
    } finally {
      setSubmitting(false)
    }
  }, [
    beginManualOperation,
    classOptions,
    executeClassSignin,
    fetchSigninHistory,
    fetchSigninTasks,
    form.selectedClassIds,
    form.signType,
    recordManualResult,
    submitting,
  ])

  const executeSelectedCourseSignin = useCallback(async () => {
    if (submitting) return
    if (form.selectedCourseIds.length === 0) {
      await executeSignin()
      return
    }
    const operation = beginManualOperation('course')
    const selected = form.selectedCourseIds.map((id) => courseOptions.find((course) => course.id === id))
    if (selected.some((course) => !course)) {
      const message = '选中的课程无效，请重新选择后再试。'
      setResultType('error')
      setResultMessage(message)
      recordManualResult(operation, 'error', message)
      return
    }
    setSubmitting(true)
    try {
      const results = []
      for (const course of selected) {
        const result = await executeSignin(course.id, form.signType, { silent: true })
        results.push({ ...result, name: course.name })
      }
      const outcome = formatBatchOutcome('课程', '门', results)
      setResultType(outcome.toastType)
      setResultMessage(outcome.message)
      recordManualResult(operation, outcome.kind, outcome.message)
      await fetchSigninTasks()
    } finally {
      setSubmitting(false)
    }
  }, [beginManualOperation, courseOptions, executeSignin, fetchSigninTasks, form.selectedCourseIds, form.signType, recordManualResult, submitting])

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
      setSigninTarget(classKey ? 'class' : 'course')
      setForm((prev) => ({
        ...prev,
        signType: detectedType,
        ...(matchedClass ? { selectedClassIds: [matchedClass.id] } : {}),
        ...(!classKey && task.courseId ? { selectedCourseIds: [String(task.courseId)] } : {}),
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

    accountGenerationRef.current += 1
    manualOperationRef.current += 1
    setLastResult(null)
    coursesRequestRef.current += 1
    classesRequestRef.current += 1
    signinTasksRequestRef.current += 1
    setSigninTasksLoading(false)
    setAccountReady(false)
    chatSignin.reset()
    setCourses([])
    setClassSubjects([])
    setSigninTasks([])
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
      setAccountReady(true)

      void fetchCourses()

      void fetchClasses()
      void fetchSigninTasks()
      setActiveTab('signin')
    } catch (err) {
      setResultType('error')

      setResultMessage(err.message || '账号验证失败。')
    } finally {
      setSubmitting(false)
    }
  }

  // A background task is "running" only while its last known status says so;
  // an unread or unrecognised status is never shown as running. Used for the
  // cross-tab progress pill and to block a second create.
  const taskRunning = Boolean(taskId) && isBackgroundTaskActive(taskStatus)
  const backgroundBusy =
    taskRunning ||
    backgroundTaskHistory.some((task) => isBackgroundTaskActive(task) && !(task.taskId === taskId && taskStatus))

  // Shared guard for both create buttons: one request at a time, and none
  // while a known task is still running. The open task's status and logs stay
  // until the server returns a new task id, so a rejection or 409 keeps them.
  const beginBackgroundCreate = () => {
    if (submitting || backgroundCreateRef.current) return false

    if (backgroundBusy) {
      setResultType('error')

      setResultMessage('后台任务运行中，结束后再创建。')

      return false
    }

    if (!form.username.trim() || !form.password) {
      setResultType('error')

      setResultMessage('请输入账号和密码。')

      return false
    }

    backgroundCreateRef.current = true

    setSubmitting(true)

    setResultMessage('')

    return true
  }

  const startSigninTask = async () => {
    if (!beginBackgroundCreate()) return

    const username = form.username.trim()

    const password = form.password

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
      backgroundCreateRef.current = false

      setSubmitting(false)
    }
  }

  const startClassSigninTask = async () => {
    if (!beginBackgroundCreate()) return

    const username = form.username.trim()

    const password = form.password

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
      backgroundCreateRef.current = false

      setSubmitting(false)
    }
  }

  const hasCredentials = Boolean(form.username.trim() && form.password)

  const openAccountTab = () => setActiveTab('account')

  const accountCard = (
    <section className="ui-index-card spine-signin space-y-4 p-4 sm:p-5" aria-labelledby="cx-account-heading">
      <div>
        <h2 id="cx-account-heading" className="font-display text-base font-bold text-text">学习通账号</h2>
        <p className="mt-1 text-sm text-text-muted">
          {accountReady ? '修改后需重新验证。' : '密码只在本页使用，不会保存。'}
        </p>
      </div>
      <form className="grid gap-4 sm:grid-cols-2" onSubmit={verifyAccount}>
        <Input id="cx-username" label="账号 / 手机号" type="text" disabled={submitting || chatSignin.submitting} name="cx-username" autoComplete="username" value={form.username} onChange={(event) => setForm((prev) => ({ ...prev, username: event.target.value }))} required />
        <Input id="cx-password" label="密码" type="password" disabled={submitting || chatSignin.submitting} name="cx-password" autoComplete="current-password" value={form.password} onChange={(event) => setForm((prev) => ({ ...prev, password: event.target.value }))} required />
        <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
          <Button type="submit" disabled={submitting || chatSignin.submitting}>{submitting ? '验证中...' : '验证账号并获取课程'}</Button>
          {accountReady && <StatusBadge status="connected" label="已验证" />}
        </div>
      </form>
    </section>
  )

  const backgroundScopeNames = {
    courses: form.selectedCourseIds.map((id) => courseOptions.find((course) => course.id === id)?.name).filter(Boolean),
    classes: form.selectedClassIds.map((id) => classOptions.find((subject) => subject.id === id)?.name).filter(Boolean),
  }

  const refreshOpenTask = () =>
    refreshTaskStatus(taskId, {
      setResultType,
      setResultMessage,
      setBackgroundTaskHistory,
    })

  const taskDetail = (
    <BackgroundTaskDetail
      taskId={taskId}
      taskStatus={taskStatus}
      logs={logs}
      statusLoading={statusLoading}
      onRefresh={refreshOpenTask}
    />
  )

  // Shown only for the account that made the request; editing the account
  // field (even before re-verifying) hides it.
  const resultNotice = lastResult && lastResult.account === form.username.trim() && (() => {
    const meta = RESULT_NOTICE[lastResult.kind] || RESULT_NOTICE.info
    return (
      <StateNotice kind={meta.kind} compact title={`${SCOPE_LABEL[lastResult.scope] || '最近一次结果'} · ${meta.title}`}>
        <p>{lastResult.message}</p>
        <p className="font-code mt-0.5 text-xs opacity-75">{lastResult.at.toLocaleTimeString('zh-CN', { hour12: false })}</p>
      </StateNotice>
    )
  })()

  // Shared by the course/class form and the group-chat location sign-in.
  const locationFields = (
                  <>
                    {/* Primary path: one tap to fill coordinates. */}
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={useCurrentLocation}
                        disabled={geocodeLoading}
                      >
                        <MapPin className="h-4 w-4" aria-hidden="true" />
                        使用当前位置
                      </Button>

                      <Button
                        type="button"
                        variant="secondary"
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
                      onChange={(e) => handleAddressChange(e.target.value)}
                      placeholder="例如：北京市朝阳区"
                    />

                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={resolveLocationCoordinates}
                        disabled={geocodeLoading}
                      >
                        {geocodeLoading ? '解析中...' : '解析坐标'}
                      </Button>

                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={searchLocationCandidates}
                        disabled={placeSearchLoading}
                      >
                        <Search className="h-3.5 w-3.5" aria-hidden="true" />
                        {placeSearchLoading ? '搜索中...' : '搜索地点'}
                      </Button>

                      {geocodeMessage && (
                        <p
                          role="status"
                          className={`text-xs font-medium ${
                            geocodeStatus === 'error'
                              ? 'text-danger'
                              : geocodeStatus === 'success'
                                ? 'text-success'
                                : 'text-text-muted'
                          }`}
                        >
                          {geocodeMessage}
                        </p>
                      )}
                    </div>

                    {placeSearchMessage ? (
                      <p className="text-xs text-text-muted">{placeSearchMessage}</p>
                    ) : null}

                    {placeSearchResults.length > 0 ? (
                      <div className="divide-y divide-border-subtle overflow-hidden rounded-lg border border-border bg-surface">
                        {placeSearchResults.map((candidate) => (
                          <button
                            key={candidate.id}
                            type="button"
                            data-place-result-id={candidate.id}
                            className="w-full px-3 py-2.5 text-left hover:bg-surface-hover focus-visible:ring-inset"
                            onClick={() => choosePlaceSearchResult(candidate)}
                          >
                            <span className="block text-sm font-semibold text-text">
                              {candidate.name || candidate.address}
                            </span>

                            <span className="mt-0.5 block text-xs text-text-muted">
                              {candidate.address}
                            </span>
                          </button>
                        ))}
                      </div>
                    ) : null}

                    {/* Manual override — pre-filled by the actions above; rarely needed. */}
                    <details className="ui-panel px-3 py-2">
                      <summary className="min-h-[32px] py-1.5 text-sm text-text-muted">
                        手动输入坐标（高级）
                      </summary>
                      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
                        <Input
                          id="cx-latitude"
                          label="纬度"
                          type="text"
                          value={form.latitude}
                          onChange={(e) => applyUserLocationIntent({ latitude: e.target.value }, { convert: false })}
                          placeholder="e.g. 39.9042"
                        />

                        <Input
                          id="cx-longitude"
                          label="经度"
                          type="text"
                          value={form.longitude}
                          onChange={(e) => applyUserLocationIntent({ longitude: e.target.value }, { convert: false })}
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
                      <p className="ui-hint mb-1">坐标使用百度 BD-09 坐标系。</p>
                    </details>
                  </>
  )

  // ── Render ─────────────────────────────────────────────────────────────────

  const showPhoto = form.signType === 'photo' || (form.signType === 'all' && advancedOpen)
  const showLocation = form.signType === 'location' || form.signType === 'qrcode' || form.signType === 'gesture' || (form.signType === 'all' && advancedOpen)
  const showQr = form.signType === 'qrcode' || (form.signType === 'all' && advancedOpen)
  const showGesture = form.signType === 'gesture' || (form.signType === 'all' && advancedOpen)
  const showCode = form.signType === 'code' || (form.signType === 'all' && advancedOpen)
  const submitBlocked = !hasCredentials || (signinTarget === 'class' && form.selectedClassIds.length === 0)

  return (
    <div className="overflow-x-hidden">
      <div className="space-y-5">
        <PageHeader
          spine="signin"
          eyebrow="学习通"
          title="课堂签到"
          actions={
            <>
              {taskRunning && (
                <button
                  type="button"
                  onClick={() => setActiveTab('monitor')}
                  className="ui-btn-secondary border-primary/40 text-primary"
                  title="查看后台任务进度"
                >
                  <span className="relative flex h-2 w-2" aria-hidden="true">
                    <span className="absolute inline-flex h-full w-full rounded-full bg-primary/60 motion-safe:animate-ping" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
                  </span>
                  后台任务进行中
                </button>
              )}
              <AccountChip ready={accountReady} account={form.username} onClick={openAccountTab} />
            </>
          }
        >
          <WorkspaceTabs id="cx" label="课堂签到工作区" tabs={CHAOXING_TABS} activeTab={activeTab} onChange={setActiveTab} />
        </PageHeader>

        {activeTab === 'account' && (
          <section id="cx-panel-account" role="tabpanel" aria-labelledby="cx-tab-account" tabIndex="0" className="max-w-3xl">
            {accountCard}
          </section>
        )}

        {activeTab === 'signin' && (
          <section id="cx-panel-signin" role="tabpanel" aria-labelledby="cx-tab-signin" tabIndex="0" className="space-y-4">
            {!accountReady ? (
              <div className="max-w-3xl">{accountCard}</div>
            ) : (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <div className="inline-flex max-w-full rounded-lg border border-border bg-surface p-1" role="group" aria-label="签到范围">
                  {SIGNIN_SCOPES.map((scope) => {
                    const Icon = scope.icon
                    const active = signinTarget === scope.id
                    return (
                      <button
                        key={scope.id}
                        type="button"
                        aria-pressed={active}
                        onClick={() => setSigninTarget(scope.id)}
                        className={`inline-flex min-h-[36px] items-center gap-1.5 rounded-md px-3.5 text-sm font-semibold transition-colors ${
                          active ? 'bg-primary text-on-primary' : 'text-text-muted hover:bg-surface-hover hover:text-text'
                        }`}
                      >
                        <Icon className="h-4 w-4" aria-hidden="true" />
                        {scope.label}
                      </button>
                    )
                  })}
                </div>
              </div>

              {signinTarget !== 'chat' && <AutoSigninBanner
                signinTasks={signinTasks}
                form={form}
                submitting={submitting}
                onApplyTask={applyDetectedTask}
                onApplyAndSubmit={applyAndSubmitDetectedTask}
                onRefresh={fetchSigninTasks}
                refreshing={signinTasksLoading}
                error={signinTasksError}
              />}

              <div className={GLASS_CARD_CLASS}>
              {signinTarget === 'chat' ? (
                <ChatSigninSection chat={chatSignin} hasCredentials={hasCredentials} busy={submitting} onOpenAccount={openAccountTab} locationFields={locationFields} />
              ) : (
              <form className="grid items-start gap-6 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]" onSubmit={(event) => { event.preventDefault(); void (signinTarget === 'class' ? executeSelectedClassSignin() : executeSelectedCourseSignin()) }}>
                <div className="min-w-0 space-y-2">
                  {signinTarget === 'course' && (
                    <MultiSelect
                      label="课程选择（可选，不选即全部课程）"
                      options={courseOptions}
                      selectedIds={form.selectedCourseIds}
                      onChange={(ids) => setForm((prev) => ({ ...prev, selectedCourseIds: ids }))}
                      emptyHint="此账号暂无课程；可在学习通加入课程后刷新"
                      headerAction={
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label="刷新课程列表"
                          title="刷新课程列表"
                          onClick={fetchCourses}
                        >
                          <RefreshCw className="h-4 w-4" aria-hidden="true" />
                        </Button>
                      }
                    />
                  )}

                  {signinTarget === 'class' && (
                    <MultiSelect
                      label="班级选择（班级签到入口）"
                      options={classOptions}
                      selectedIds={form.selectedClassIds}
                      onChange={(ids) => setForm((prev) => ({ ...prev, selectedClassIds: ids }))}
                      emptyHint="此账号暂无班级；可在学习通加入班级后刷新"
                      headerAction={
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label="刷新班级列表"
                          title="刷新班级列表"
                          onClick={fetchClasses}
                        >
                          <RefreshCw className="h-4 w-4" aria-hidden="true" />
                        </Button>
                      }
                    />
                  )}
                </div>

                <div className="min-w-0 space-y-4">
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

                  {form.signType === 'all' && (
                    <button
                      type="button"
                      onClick={() => setAdvancedOpen((open) => !open)}
                      aria-expanded={advancedOpen}
                      className="ui-panel flex min-h-[40px] w-full items-center justify-between px-3 py-2 text-sm text-text-muted hover:text-text"
                    >
                      <span>补充签到参数（可选）</span>
                      <ChevronDown
                        className={`h-4 w-4 shrink-0 transition-transform ${advancedOpen ? 'rotate-180' : ''}`}
                        aria-hidden="true"
                      />
                    </button>
                  )}

                  {showPhoto && (
                    <div>
                      <label htmlFor="cx-photo" className="ui-label">
                        签到照片（自拍/拍照）
                      </label>

                      <div className="flex flex-wrap items-center gap-3">
                        <label className="ui-btn-secondary focus-within:ring-2 focus-within:ring-primary focus-within:ring-offset-2 focus-within:ring-offset-background">
                          <Camera className="h-4 w-4" aria-hidden="true" />
                          选择照片
                          <input
                            id="cx-photo"
                            type="file"
                            accept="image/jpeg,image/png,image/webp"
                            className="sr-only"
                            onChange={(event) => {
                              const file = event.target.files?.[0] || null
                              try {
                                validatePhotoFile(file)
                                setForm((prev) => ({ ...prev, photoFile: file }))
                              } catch (error) {
                                event.target.value = ''
                                toast.error(error.message)
                              }
                            }}
                          />
                        </label>

                        <p className="text-xs text-text-muted">
                          {form.photoFile
                            ? `已选择：${form.photoFile.name}（${(form.photoFile.size / 1024).toFixed(0)} KB）`
                            : '请上传自拍照片，支持 JPG、PNG、WebP，最大 5 MB。'}
                        </p>
                      </div>

                      {photoPreviewUrl && (
                        <img
                          src={photoPreviewUrl}
                          alt="签到照片预览"
                          className="mt-3 h-28 w-28 rounded-md border border-border object-cover"
                        />
                      )}
                    </div>
                  )}

                  {showLocation && (
                    <fieldset className="ui-panel space-y-3 p-3.5">
                      <legend className="px-1 text-xs font-semibold text-text">位置</legend>
                      {locationFields}
                    </fieldset>
                  )}

                  {showQr && (
                    <div className="space-y-3">
                      <div>
                        <label
                          htmlFor="cx-qrcode-file"
                          className="ui-label"
                        >
                          上传二维码图片
                        </label>

                        <div className="flex flex-wrap items-center gap-3">
                          <label className="ui-btn-secondary focus-within:ring-2 focus-within:ring-primary focus-within:ring-offset-2 focus-within:ring-offset-background">
                            <Upload className="h-4 w-4" aria-hidden="true" />
                            选择二维码图片
                            <input
                              id="cx-qrcode-file"
                              type="file"
                              accept="image/*"
                              className="sr-only"
                              onChange={(e) => {
                                const file = e.target.files?.[0]

                                if (file) handleQrCodeFileUpload(file)
                              }}
                            />
                          </label>

                          <p
                            role="status"
                            className={`text-xs font-medium ${form.qrDecodeStatus.includes('成功') ? 'text-success' : form.qrDecodeStatus.includes('失败') || form.qrDecodeStatus.includes('无法') ? 'text-danger' : 'text-text-muted'}`}
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
                        label="二维码内容"
                        type="text"
                        value={form.qrCode}
                        onChange={(e) => {
                          qrDecodeGenerationRef.current += 1
                          setForm((prev) => ({ ...prev, qrCode: e.target.value, qrDecodeStatus: '' }))
                        }}
                        placeholder="粘贴二维码链接或内容"
                        hint="二维码签到可附带经纬度、地址和海拔参数以提高成功率。"
                      />
                    </div>
                  )}

                  {showGesture && (
                    <Input
                      id="cx-gesture"
                      label="手势编码"
                      type="text"
                      value={form.gesturePattern}
                      onChange={(e) =>
                        setForm((prev) => ({ ...prev, gesturePattern: e.target.value }))
                      }
                      placeholder="请输入老师发布的手势编码"
                      hint="手势签到可附带位置参数，填写上方地址信息以提高成功率。"
                    />
                  )}

                  {showCode && (
                    <Input
                      id="cx-sign-code"
                      label="签到码"
                      type="text"
                      value={form.signCode}
                      onChange={(e) => setForm((prev) => ({ ...prev, signCode: e.target.value }))}
                      placeholder="请输入老师发布的签到码"
                    />
                  )}

                  <div className="flex flex-wrap items-center gap-3 border-t border-border-subtle pt-4">
                    <Button type="submit" disabled={submitting || submitBlocked}>
                      {submitting ? '签到中...' : signinTarget === 'class' ? '班级签到' : '课程签到'}
                    </Button>
                    {!hasCredentials && <p className="text-sm text-text-muted">请先在「账号」中填写密码。</p>}
                    {hasCredentials && signinTarget === 'class' && form.selectedClassIds.length === 0 && (
                      <p className="text-sm text-text-muted">先选择至少一个班级。</p>
                    )}
                  </div>

                  {resultNotice}
                </div>
              </form>
              )}
              </div>
            </>
            )}
          </section>
        )}

        {activeTab === 'monitor' && (
          <section id="cx-panel-monitor" role="tabpanel" aria-labelledby="cx-tab-monitor" tabIndex="0" className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
            <div className="min-w-0 space-y-4">
              <ConfigTab autoSignin={autoSignin} setAutoSignin={setAutoSignin} autoSignFilter={autoSignFilter} setAutoSignFilter={setAutoSignFilter} checkInterval={checkInterval} setCheckInterval={setCheckInterval} nextCheckCountdown={nextCheckCountdown} paused={!accountReady} />
              <section className={`${GLASS_CARD_CLASS} space-y-4`} aria-labelledby="cx-bg-create-heading">
                <div>
                  <h2 id="cx-bg-create-heading" className="font-display text-base font-bold text-text">后台签到任务</h2>
                  <p className="mt-1 text-sm text-text-muted">签到类型：{getSignTypeLabel(form.signType)}</p>
                </div>

                <dl className="grid gap-3 sm:grid-cols-2">
                  {[
                    { label: '课程范围', names: backgroundScopeNames.courses, empty: '未选课程' },
                    { label: '班级范围', names: backgroundScopeNames.classes, empty: '未选班级' },
                  ].map((scope) => (
                    <div key={scope.label} className="ui-panel px-3 py-2.5">
                      <dt className="catalog-label">{scope.label}</dt>
                      <dd className="mt-1 text-sm text-text">
                        {scope.names.length > 0 ? (
                          <span className="line-clamp-3 break-words">{scope.names.join('、')}</span>
                        ) : (
                          <span className="text-text-muted">{scope.empty}</span>
                        )}
                      </dd>
                    </div>
                  ))}
                </dl>

                {hasCredentials ? (
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" onClick={startSigninTask} disabled={submitting || backgroundBusy || form.selectedCourseIds.length === 0}>{submitting ? '处理中...' : '创建课程任务'}</Button>
                    <Button type="button" variant="secondary" onClick={startClassSigninTask} disabled={submitting || backgroundBusy || form.selectedClassIds.length === 0}>{submitting ? '处理中...' : '创建班级任务'}</Button>
                    <Button type="button" variant="ghost" onClick={() => setActiveTab('signin')}>调整范围与参数</Button>
                  </div>
                ) : (
                  <p className="text-sm text-text-muted">
                    请先在
                    <button type="button" className="mx-1 font-semibold text-primary underline-offset-4 hover:underline" onClick={openAccountTab}>账号</button>
                    中验证学习通账号。
                  </p>
                )}
                <p className="ui-hint mt-0">{backgroundBusy ? '后台任务运行中，结束后可再创建。' : '同一账号同时只运行一个后台任务。'}</p>
              </section>
            </div>
            <div className="min-w-0 lg:sticky lg:top-20">{taskDetail}</div>
          </section>
        )}

        {activeTab === 'tasks' && (
          <section id="cx-panel-tasks" role="tabpanel" aria-labelledby="cx-tab-tasks" tabIndex="0" className="space-y-4">
            <TasksTab
              signinTasks={signinTasks}
              fetchSigninTasks={fetchSigninTasks}
              refreshing={signinTasksLoading}
              error={signinTasksError}
              accountReady={accountReady}
              onOpenAccount={openAccountTab}
              openBackgroundTask={(tid) => {
                setActiveTab('monitor')
                // The clicked button unmounts with this tab; land focus on the
                // task detail instead of dropping it to the page body.
                window.requestAnimationFrame?.(() => document.getElementById('cx-task-detail-heading')?.focus())
                return openBackgroundTask(tid, {
                  setResultType,
                  setResultMessage,
                  setBackgroundTaskHistory,
                })
              }}
              onApplyTask={(task) => { applyDetectedTask(task); setActiveTab('signin') }}
              executeSignin={executeSignin}
              executeClassSignin={executeClassSignin}
            />
          </section>
        )}

        {activeTab === 'history' && (
          <section id="cx-panel-history" role="tabpanel" aria-labelledby="cx-tab-history" tabIndex="0" className="space-y-4">
              <StatsCards todayStats={todayStats} />
              <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,23rem)_minmax(0,1fr)]">
                <section className={GLASS_CARD_CLASS} aria-labelledby="cx-bg-history-heading">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                    <h2 id="cx-bg-history-heading" className="font-display text-base font-bold text-text">后台任务历史</h2>

                    <Button
                      type="button"
                      variant="secondary"
                      size="icon"
                      aria-label="刷新后台任务历史"
                      title="刷新后台任务历史"
                      onClick={() => {
                        void fetchBackgroundTaskHistory()
                      }}
                    >
                      <RefreshCw className="h-4 w-4" aria-hidden="true" />
                    </Button>
                  </div>

                  {backgroundTaskHistory.length === 0 ? (
                    <StateNotice kind="empty" compact>暂无后台任务历史</StateNotice>
                  ) : (
                    <ul className="max-h-[32rem] space-y-2 overflow-y-auto pr-0.5">
                      {backgroundTaskHistory.map((task) => {
                        const isActive = task.taskId === taskId
                        return (
                          <li key={task.taskId}>
                            <button
                              type="button"
                              aria-pressed={isActive}
                              className={`w-full rounded-lg border px-3 py-2.5 text-left ${isActive ? 'border-primary/60 bg-primary/5' : 'border-border-subtle bg-surface hover:border-primary/40 hover:bg-surface-hover'}`}
                              onClick={() => {
                                void openBackgroundTask(task.taskId, {
                                  setResultType,
                                  setResultMessage,
                                  setBackgroundTaskHistory,
                                })
                                historyDetailRef.current?.scrollIntoView?.({ block: 'start' })
                              }}
                            >
                              <span className="flex flex-wrap items-start justify-between gap-2">
                                <span className="min-w-0 flex-1">
                                  <span className="block text-sm font-semibold text-text">
                                    {task.courseName || '后台签到任务'}
                                  </span>
                                  <span className="font-code mt-0.5 block break-all text-xs text-text-muted">
                                    任务 ID：{task.taskId}
                                  </span>
                                </span>
                                {(() => {
                                  const badge = backgroundTaskBadge(task)
                                  return <StatusBadge status={badge.status} label={badge.label} />
                                })()}
                              </span>
                              {task.message && <span className="mt-1.5 block text-xs text-text-muted">{task.message}</span>}
                              <span className="font-code mt-1 block text-[0.6875rem] text-text-muted">
                                更新时间：
                                {parseTaskTimestamp(task.updatedAt || task.createdAt) > 0
                                  ? new Date(task.updatedAt || task.createdAt).toLocaleString()
                                  : '--'}
                              </span>
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </section>
                <div ref={historyDetailRef} className="min-w-0 lg:sticky lg:top-20">{taskDetail}</div>
              </div>
              <HistoryTab signinHistory={signinHistory} fetchSigninHistory={fetchSigninHistory} />
          </section>
        )}
      </div>

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
              applyUserLocationIntent(location)
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
