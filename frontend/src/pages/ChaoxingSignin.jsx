import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { AlertCircle, CheckCircle2, Loader2, Camera, RefreshCw, Upload } from 'lucide-react'

import { getToken, isAuthenticated, removeToken } from '../utils/auth'

import { Button, Input } from '../components'

import BaiduMapPickerModal from '../components/BaiduMapPickerModal'

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
  getCourseDisplayName,
  parseTaskTimestamp,
} from './chaoxing-signin/utils'

import useBackgroundTasks from './chaoxing-signin/hooks/useBackgroundTasks'
import useAutoSignin from './chaoxing-signin/hooks/useAutoSignin'
import useLocationServices from './chaoxing-signin/hooks/useLocationServices'

import StatsCards from './chaoxing-signin/components/StatsCards'
import TasksTab from './chaoxing-signin/components/TasksTab'
import HistoryTab from './chaoxing-signin/components/HistoryTab'
import ConfigTab from './chaoxing-signin/components/ConfigTab'



export default function ChaoxingSignin() {

  const navigate = useNavigate()

  const ensureAccessTokenRef = useRef(null)

  const redirectToLoginRef = useRef(null)

  const redirectingRef = useRef(false)

  const setTodayStatsRef = useRef(null)



  const [submitting, setSubmitting] = useState(false)

  const [resultMessage, setResultMessage] = useState('')

  const [resultType, setResultType] = useState('info')

  const [activeTab, setActiveTab] = useState('signin')

  const [courses, setCourses] = useState([])

  const [signinTasks, setSigninTasks] = useState([])

  const [signinHistory, setSigninHistory] = useState([])

  const [backgroundTaskHistory, setBackgroundTaskHistory] = useState([])

  const [form, setForm] = useState({

    username: '',

    password: '',

    selectedCourseIds: [],

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

    gesturePattern: ''

  })



  const ensureAccessToken = useCallback(() => {

    return getToken() || null

  }, [])



  const redirectToLogin = useCallback((message = '登录已过期，请重新登录。') => {

    if (!redirectingRef.current) {

      redirectingRef.current = true

      removeToken()

      navigate('/login', { replace: true })

    }

    throw new Error(message)

  }, [navigate])



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

        Authorization: `Bearer ${token}`

      }



      if (hasBody && !isFormData && !headers['Content-Type']) {

        headers['Content-Type'] = 'application/json'

      }



      const response = await fetch(`${CHAOXING_API_BASE}${path}`, {

        ...options,

        method,

        headers,

        body: hasBody ? (isFormData ? body : JSON.stringify(body)) : undefined

      })



      const payload = await parsePayload(response)

      const message = pickMessage(payload)

      const code = payload?.code || payload?.error_code

      const isAuthFailure =

        response.status === 401 ||

        response.status === 403 ||

        code === 'AUTH_TOKEN_EXPIRED' ||

        code === 'AUTH_INVALID_TOKEN' ||

        (response.status === 200 && payload?.status === false && TOKEN_ERROR_PATTERN.test(message || ''))

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

    []

  )



  // ── Hooks ──────────────────────────────────────────────────────────────────

  const backgroundTasks = useBackgroundTasks(requestChaoxingApi)
  const {
    taskId, setTaskId, taskStatus, setTaskStatus,
    logs, setLogs, statusLoading,
    refreshTaskStatus, openBackgroundTask, stopPolling,
  } = backgroundTasks

  const locationServices = useLocationServices(requestChaoxingApi, setForm)
  const {
    latestAddressRef,
    geocodeLoading, geocodeMessage, geocodeStatus,
    setGeocodeStatus, setGeocodeMessage,
    placeSearchLoading, placeSearchResults, placeSearchMessage,
    isMapPickerOpen, setIsMapPickerOpen,
    applyResolvedLocation,
    resolveLocationCoordinates, searchLocationCandidates, choosePlaceSearchResult,
  } = locationServices



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

      const todayRecords = (resp?.data || []).filter(r => new Date(r.timestamp).toDateString() === today)

      if (setTodayStatsRef.current) {
        setTodayStatsRef.current({

          total: todayRecords.length,

          success: todayRecords.filter(r => r.status === 'success').length,

          failed: todayRecords.filter(r => r.status === 'failed').length

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



  const buildSigninPayload = useCallback((courseId = null, signTypeOverride = null) => {

    const signType = signTypeOverride || form.signType

    const payload = {

      username: form.username.trim(),

      password: form.password,

      sign_type: normalizeSignTypeForApi(signType),

      course_id: courseId

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

  }, [form])



  const executeSignin = useCallback(async (courseId = null, signTypeOverride = null, options = {}) => {

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

      let resp



      if (signType === 'photo') {

        if (!form.photoFile) {

          throw new Error('拍照签到需要先上传图片。')

        }

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

        const photoBase64 = await fileToBase64(form.photoFile)

        payload.photo_base64 = photoBase64

      }

      resp = await requestChaoxingApi('/sign', payload)



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

  }, [buildSigninPayload, fetchSigninHistory, form.password, form.photoFile, form.username, requestChaoxingApi])



  // ── Auto-signin hook (depends on executeSignin) ────────────────────────────

  const autoSigninHook = useAutoSignin(form, executeSignin, requestChaoxingApi, {
    setResultType,
    setResultMessage,
    setSigninTasks,
    redirectingRef,
  })
  const {
    autoSignin, setAutoSignin,
    autoSignFilter, setAutoSignFilter,
    checkInterval, setCheckInterval,
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

  useEffect(() => {

    if (!isAuthenticated()) {

      navigate('/login', { replace: true })

      return undefined

    }



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

        fetchSigninTasks(),

        fetchSigninHistory(),

        fetchBackgroundTaskHistory()

      ])

      if (cancelled) return

      const backgroundTasksResult = results[3]

      if (backgroundTasksResult.status !== 'fulfilled') return

      const bgTasks = Array.isArray(backgroundTasksResult.value) ? backgroundTasksResult.value : []

      if (bgTasks.length === 0) return

      const runningTask = bgTasks.find((task) => isBackgroundTaskRunning(task.status))

      const latestTask = runningTask || bgTasks[0]

      if (latestTask?.taskId) {

        await openBackgroundTask(latestTask.taskId, { setResultType, setResultMessage, setBackgroundTaskHistory })

      }

    }



    bootstrap()



    return () => {

      cancelled = true

      stopPolling()

      stopAutoCheck()

    }

  }, [ensureAccessToken, navigate, stopPolling, stopAutoCheck, fetchCourses, fetchSigninTasks, fetchSigninHistory, fetchBackgroundTaskHistory, openBackgroundTask])



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

        name: getCourseDisplayName(course, `课程 ${index + 1}`)

      })

    })



    return options

  }, [courses])



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

        use_cookies: false

      })

      setResultType('success')

      setResultMessage(pickMessage(resp) || '账号验证成功。')

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

      if (form.selectedCourseIds.length > 0 && selectedCourseOptions.length !== form.selectedCourseIds.length) {
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

        ocr_config: {}

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

          updated_at: new Date().toISOString()

        })

      )

      await openBackgroundTask(nextTaskId, { setResultType, setResultMessage, setBackgroundTaskHistory })

      void fetchBackgroundTaskHistory()

    } catch (err) {

      setResultType('error')

      setResultMessage(err.message || '启动签到任务失败。')

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



  // ── Render ─────────────────────────────────────────────────────────────────

  return (

    <div className="min-h-screen overflow-x-hidden bg-background p-4 md:p-6">

      <main className="mx-auto max-w-7xl space-y-6">

        <div className={GLASS_CARD_CLASS}>

          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">

            <div>

              <h1 className="text-2xl font-bold text-text">学习通签到</h1>

              <p className="text-sm text-text/70">完整签到功能与实时监控。</p>

            </div>

            <Button

              type="button"

              variant="secondary"

              className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 hover:scale-105"

              onClick={() => navigate('/dashboard')}

            >

              返回

            </Button>

          </div>

        </div>



        <StatsCards todayStats={todayStats} />



        <div className={GLASS_CARD_CLASS}>

          <div className="flex flex-wrap gap-2 border-b border-white/20 pb-4">

            <button

              onClick={() => setActiveTab('signin')}

              className={`min-h-[44px] rounded-xl px-4 py-2 font-medium transition-all duration-200 cursor-pointer ${

                activeTab === 'signin'

                  ? 'bg-primary text-white'

                  : 'bg-white/60 text-text hover:bg-white/80'

              }`}

            >

              签到

            </button>

            <button

              onClick={() => setActiveTab('tasks')}

              className={`min-h-[44px] rounded-xl px-4 py-2 font-medium transition-all duration-200 cursor-pointer ${

                activeTab === 'tasks'

                  ? 'bg-primary text-white'

                  : 'bg-white/60 text-text hover:bg-white/80'

              }`}

            >

              任务

            </button>

            <button

              onClick={() => setActiveTab('history')}

              className={`min-h-[44px] rounded-xl px-4 py-2 font-medium transition-all duration-200 cursor-pointer ${

                activeTab === 'history'

                  ? 'bg-primary text-white'

                  : 'bg-white/60 text-text hover:bg-white/80'

              }`}

            >

              历史

            </button>

            <button

              onClick={() => setActiveTab('config')}

              className={`min-h-[44px] rounded-xl px-4 py-2 font-medium transition-all duration-200 cursor-pointer ${

                activeTab === 'config'

                  ? 'bg-primary text-white'

                  : 'bg-white/60 text-text hover:bg-white/80'

              }`}

            >

              设置

            </button>

          </div>



          {activeTab === 'signin' && (

            <div className="mt-6 space-y-4">

              <form className="grid grid-cols-1 gap-4 md:grid-cols-2" onSubmit={verifyAccount}>

            <Input

              id="cx-username"

              label="账号 / 手机号"

              type="text"

              value={form.username}

              onChange={(event) => setForm((prev) => ({ ...prev, username: event.target.value }))}

              required

            />

            <Input

              id="cx-password"

              label="密码"

              type="password"

              value={form.password}

              onChange={(event) => setForm((prev) => ({ ...prev, password: event.target.value }))}

              required

            />

            <div className="md:col-span-2">

              <label htmlFor="cx-signtype" className="mb-2 block text-sm font-medium text-text">

                签到类型

              </label>

              <select

                id="cx-signtype"

                value={form.signType}

                onChange={(event) => setForm((prev) => ({ ...prev, signType: event.target.value }))}

                className="w-full min-h-[44px] rounded-xl border border-white/30 bg-white/60 px-4 py-2 text-text backdrop-blur-sm transition-all duration-200 hover:border-primary/50 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 cursor-pointer"

              >

                <option value="all">全部类型</option>

                <option value="normal">普通签到</option>

                <option value="photo">拍照签到</option>

                <option value="location">位置签到</option>

                <option value="qrcode">二维码签到</option>

                <option value="gesture">手势签到</option>

                <option value="code">签到码签到</option>

              </select>

            </div>

            <div className="md:col-span-2">

              <div className="mb-2 flex items-center justify-between gap-2">

                <label htmlFor="cx-courselist" className="block text-sm font-medium text-text">

                  课程选择（可选，不选即全部课程）

                </label>

                <Button

                  type="button"

                  variant="secondary"

                  className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 hover:scale-105"

                  onClick={fetchCourses}

                >

                  <RefreshCw className="h-4 w-4" />

                </Button>

              </div>

              <select

                id="cx-courselist"

                multiple

                value={form.selectedCourseIds}

                onChange={(event) => {

                  const nextSelected = Array.from(event.target.selectedOptions).map((option) => option.value)

                  setForm((prev) => ({ ...prev, selectedCourseIds: nextSelected }))

                }}

                className="w-full min-h-[180px] rounded-xl border border-white/30 bg-white/60 px-4 py-2 text-text backdrop-blur-sm transition-all duration-200 hover:border-primary/50 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 cursor-pointer"

              >

                {courseOptions.length === 0 ? (

                  <option value="" disabled>暂无课程，请先验证账号后刷新课程</option>

                ) : (

                  courseOptions.map((course) => (

                    <option key={course.id} value={course.id}>

                      {course.name}

                    </option>

                  ))

                )}

              </select>

              <div className="mt-2 flex flex-wrap items-center gap-2">

                <Button

                  type="button"

                  variant="secondary"

                  className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 hover:scale-105"

                  onClick={() => {

                    setForm((prev) => ({ ...prev, selectedCourseIds: courseOptions.map((course) => course.id) }))

                  }}

                  disabled={courseOptions.length === 0}

                >

                  全选

                </Button>

                <Button

                  type="button"

                  variant="secondary"

                  className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 hover:scale-105"

                  onClick={() => {

                    setForm((prev) => ({ ...prev, selectedCourseIds: [] }))

                  }}

                >

                  清空

                </Button>

                <p className="text-xs text-text/70">

                  已选 {form.selectedCourseIds.length} 门，已加载 {courseOptions.length} 门课程

                </p>

              </div>

            </div>

                {(form.signType === 'photo' || form.signType === 'all') && (

                  <div className="md:col-span-2">

                    <label htmlFor="cx-photo" className="mb-2 block text-sm font-medium text-text">

                      签到照片（自拍/拍照）

                    </label>

                    <div className="flex items-center gap-3">

                      <label

                        htmlFor="cx-photo"

                        className="flex min-h-[44px] cursor-pointer items-center gap-2 rounded-xl border border-white/30 bg-white/60 px-4 py-2 text-sm text-text backdrop-blur-sm transition-all duration-200 hover:border-primary/50 hover:bg-white/80"

                      >

                        <Camera className="h-4 w-4" />

                        选择照片

                      </label>

                      <input

                        id="cx-photo"

                        type="file"

                        accept="image/*"

                        className="hidden"

                        onChange={(event) => setForm((prev) => ({ ...prev, photoFile: event.target.files?.[0] || null }))}

                      />

                      <p className="text-xs text-text/70">

                        {form.photoFile ? `已选择：${form.photoFile.name}（${(form.photoFile.size / 1024).toFixed(0)} KB）` : '请上传自拍照片，支持 JPG/PNG 格式。'}

                      </p>

                    </div>

                    {form.photoFile && (

                      <div className="mt-3">

                        <img

                          src={URL.createObjectURL(form.photoFile)}

                          alt="预览"

                          className="h-32 w-32 rounded-xl border border-white/30 object-cover"

                        />

                      </div>

                    )}

                  </div>

                )}

                {(form.signType === 'location' || form.signType === 'qrcode' || form.signType === 'gesture' || form.signType === 'all') && (

                  <>

                    <Input

                      id="cx-latitude"

                      label="纬度"

                      type="text"

                      value={form.latitude}

                      onChange={(e) => setForm((prev) => ({ ...prev, latitude: e.target.value }))}

                      placeholder="e.g. 39.9042"

                    />

                    <Input

                      id="cx-longitude"

                      label="经度"

                      type="text"

                      value={form.longitude}

                      onChange={(e) => setForm((prev) => ({ ...prev, longitude: e.target.value }))}

                      placeholder="e.g. 116.4074"

                    />

                    <div className="md:col-span-2">

                      <Input

                        id="cx-address"

                        label="地址"

                        type="text"

                        value={form.address}

                        onChange={(e) => {
                          latestAddressRef.current = e.target.value
                          setForm((prev) => ({ ...prev, address: e.target.value }))
                        }}

                        placeholder="e.g. Chaoyang District, Beijing"

                      />

                      <div className="mt-3 flex flex-wrap items-center gap-3">

                        <Button

                          type="button"

                          variant="secondary"

                          className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 hover:scale-105 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:scale-100"

                          onClick={resolveLocationCoordinates}


                          disabled={geocodeLoading}

                        >

                          {geocodeLoading ? '解析中...' : '解析坐标'}

                        </Button>

                        <Button

                          type="button"

                          variant="secondary"

                          className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 hover:scale-105 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:scale-100"

                          onClick={searchLocationCandidates}

                          disabled={placeSearchLoading}

                        >

                          {placeSearchLoading ? '搜索中...' : '搜索地点'}

                        </Button>

                        <Button

                          type="button"

                          variant="secondary"

                          className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 hover:scale-105"

                          onClick={() => setIsMapPickerOpen(true)}

                        >

                          地图选点

                        </Button>

                        <p

                          className={`text-xs ${

                            geocodeStatus === 'error'

                              ? 'text-red-600'

                              : geocodeStatus === 'success'

                                ? 'text-green-600'

                                : 'text-text/70'

                          }`}

                        >

                          {geocodeMessage || '可根据地点名称自动补全经纬度。'}

                        </p>

                      </div>

                      {placeSearchMessage ? (

                        <p className="mt-3 text-xs text-text/70">{placeSearchMessage}</p>

                      ) : null}

                      {placeSearchResults.length > 0 ? (

                        <div className="mt-3 space-y-2 rounded-xl border border-white/30 bg-white/50 p-3 backdrop-blur-sm">

                          {placeSearchResults.map((candidate) => (

                            <button

                              key={candidate.id}

                              type="button"

                              data-place-result-id={candidate.id}

                              className="w-full rounded-xl border border-transparent bg-white/70 px-4 py-3 text-left transition-all duration-200 hover:border-primary/40 hover:bg-white"

                              onClick={() => choosePlaceSearchResult(candidate)}

                            >

                              <span className="block text-sm font-medium text-text">{candidate.name || candidate.address}</span>

                              <span className="mt-1 block text-xs text-text/70">{candidate.address}</span>

                            </button>

                          ))}

                        </div>

                      ) : null}

                    </div>

                    <Input

                      id="cx-altitude"

                      label="海拔（米）"

                      type="number"

                      step="0.1"

                      value={form.altitude}

                      onChange={(e) => setForm((prev) => ({ ...prev, altitude: e.target.value }))}

                      placeholder="默认 100"

                    />

                  </>

                )}

                {(form.signType === 'qrcode' || form.signType === 'all') && (

                  <div className="md:col-span-2 space-y-4">

                    <div>

                      <label htmlFor="cx-qrcode-file" className="mb-2 block text-sm font-medium text-text">

                        上传二维码图片

                      </label>

                      <div className="flex items-center gap-3">

                        <label

                          htmlFor="cx-qrcode-file"

                          className="flex min-h-[44px] cursor-pointer items-center gap-2 rounded-xl border border-white/30 bg-white/60 px-4 py-2 text-sm text-text backdrop-blur-sm transition-all duration-200 hover:border-primary/50 hover:bg-white/80"

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

                        <p className={`text-xs ${form.qrDecodeStatus.includes('成功') ? 'text-green-600' : form.qrDecodeStatus.includes('失败') || form.qrDecodeStatus.includes('无法') ? 'text-red-600' : 'text-text/70'}`}>

                          {form.qrDecodeStatus || (form.qrCodeFile ? `已选择：${form.qrCodeFile.name}` : '支持 JPG/PNG 格式的二维码截图')}

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

                {(form.signType === 'gesture' || form.signType === 'all') && (

                  <div className="md:col-span-2">

                    <Input

                      id="cx-gesture"

                      label="手势编码"

                      type="text"

                      value={form.gesturePattern}

                      onChange={(e) => setForm((prev) => ({ ...prev, gesturePattern: e.target.value }))}

                      placeholder="请输入老师发布的手势编码"

                    />

                    <p className="mt-2 text-xs text-text/70">

                      手势签到可附带位置参数，填写下方地址信息以提高成功率。

                    </p>

                  </div>

                )}

                {(form.signType === 'code' || form.signType === 'all') && (

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

                <div className="md:col-span-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">

                  <Button

                    type="submit"

                    variant="secondary"

                    className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 hover:scale-105 disabled:opacity-60 disabled:cursor-not-allowed disabled:hover:scale-100"

                    disabled={submitting}

                  >

                    {submitting ? '验证中...' : '验证账号'}

                  </Button>

                  <Button

                    type="button"

                    className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 hover:scale-105 disabled:opacity-60 disabled:cursor-not-allowed disabled:hover:scale-100"

                    onClick={() => executeSignin()}

                    disabled={submitting}

                  >

                    {submitting ? '签到中...' : '一键签到'}

                  </Button>

                  <Button

                    type="button"

                    variant="cta"

                    className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 hover:scale-105 disabled:opacity-60 disabled:cursor-not-allowed disabled:hover:scale-100"

                    onClick={startSigninTask}

                    disabled={submitting}

                  >

                    {submitting ? '处理中...' : '启动任务'}

                  </Button>

                  <Button

                    type="button"

                    variant="secondary"

                    className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 hover:scale-105"

                    onClick={() => navigate('/chaoxing-fanya')}

                  >

                    打开泛雅页面

                  </Button>

                </div>

              </form>



              {resultMessage && (

                <div

                  className={`mt-4 rounded-xl border p-3 text-sm backdrop-blur-sm transition-all duration-200 ${

                    resultType === 'success'

                      ? 'border-green-500/30 bg-green-50/80 text-green-700'

                      : resultType === 'error'

                        ? 'border-red-500/30 bg-red-50/80 text-red-700'

                        : 'border-primary/20 bg-white/60 text-text'

                  }`}

                >

                  <p className="flex items-center gap-2">

                    {resultType === 'success' ? (

                      <CheckCircle2 className="h-4 w-4" />

                    ) : resultType === 'error' ? (

                      <AlertCircle className="h-4 w-4" />

                    ) : (

                      <Loader2 className="h-4 w-4 animate-spin" />

                    )}

                    {resultMessage}

                  </p>

                </div>

              )}



              {(taskId || taskStatus || logs.length > 0) && (

                <div className={GLASS_PANEL_CLASS}>

                  <div className="mb-3 flex flex-wrap items-center justify-between gap-3">

                    <h3 className="text-base font-semibold text-text">任务状态</h3>

                    <Button

                      type="button"

                      variant="secondary"

                      className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 hover:scale-105 disabled:opacity-60 disabled:cursor-not-allowed disabled:hover:scale-100"

                      onClick={() => refreshTaskStatus(taskId, { setResultType, setResultMessage, setBackgroundTaskHistory })}

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

                    <pre className="mb-3 max-h-48 overflow-auto rounded-xl border border-white/20 bg-slate-900/90 p-3 text-xs text-slate-100">

                      {taskPretty}

                    </pre>

                  )}



                  <div>

                    <p className="mb-2 text-sm font-medium text-text">实时日志</p>

                    <div className="max-h-56 space-y-1 overflow-y-auto rounded-xl border border-white/20 bg-slate-900/90 p-3 font-mono text-xs text-slate-100">

                      {logs.length === 0 ? (

                        <p className="text-slate-300">暂无日志</p>

                      ) : (

                        logs.map((log, index) => {

                          const message = typeof log === 'string' ? log : (log?.message || safeStringify(log))

                          const timestamp = typeof log === 'object' && log?.timestamp ? String(log.timestamp) : ''

                          return (

                            <p key={`${timestamp}-${index}`} className="break-all">

                              {timestamp ? `[${timestamp}] ` : ''}{message}

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

                    className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200 hover:scale-105"

                    onClick={() => {

                      void fetchBackgroundTaskHistory()

                    }}

                  >

                    <RefreshCw className="h-4 w-4" />

                  </Button>

                </div>

                {backgroundTaskHistory.length === 0 ? (

                  <p className="text-sm text-text/70">暂无后台任务历史</p>

                ) : (

                  <div className="max-h-64 space-y-2 overflow-y-auto">

                    {backgroundTaskHistory.map((task) => {

                      const isActive = task.taskId === taskId

                      const statusClassName = task.status === 'completed'

                        ? 'border-green-300 bg-green-50 text-green-700'

                        : task.status === 'error'

                          ? 'border-red-300 bg-red-50 text-red-700'

                          : 'border-amber-300 bg-amber-50 text-amber-700'

                      return (

                        <button

                          key={task.taskId}

                          type="button"

                          className={`w-full min-h-[44px] rounded-xl border px-3 py-3 text-left transition-all duration-200 cursor-pointer ${isActive ? 'border-primary/50 bg-primary/10' : 'border-white/30 bg-white/70 hover:border-primary/40'}`}

                          onClick={() => {

                            void openBackgroundTask(task.taskId, { setResultType, setResultMessage, setBackgroundTaskHistory })

                          }}

                        >

                          <div className="flex flex-wrap items-start justify-between gap-2">

                            <div className="min-w-0 flex-1">

                              <p className="font-medium text-text">{task.courseName || '后台签到任务'}</p>

                              <p className="mt-1 break-all font-mono text-xs text-text/70">任务 ID：{task.taskId}</p>

                            </div>

                            <span className={`rounded-full border px-2 py-1 text-xs font-medium ${statusClassName}`}>

                              {task.status || 'unknown'}

                            </span>

                          </div>

                          <p className="mt-2 text-sm text-text/80">{task.message || '暂无消息'}</p>

                          <p className="mt-1 text-xs text-text/60">

                            更新时间：{parseTaskTimestamp(task.updatedAt || task.createdAt) > 0 ? new Date(task.updatedAt || task.createdAt).toLocaleString() : '--'}

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
              openBackgroundTask={(tid) => openBackgroundTask(tid, { setResultType, setResultMessage, setBackgroundTaskHistory })}
              executeSignin={executeSignin}
            />
          )}



          {activeTab === 'history' && (
            <HistoryTab
              signinHistory={signinHistory}
              fetchSigninHistory={fetchSigninHistory}
            />
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

    </div>

  )

}
