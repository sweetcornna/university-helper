import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BookOpen, Loader2, RefreshCw } from 'lucide-react'

import { AccountChip, EmptyState, PageHeader, useToast } from '../components'
import WorkspaceTabs from '../components/WorkspaceTabs'
import useWorkspaceTab from '../components/useWorkspaceTab'
import { translateTaskMessage } from '../utils/taskMessages'

import { CARD, RESTORE_STATUSES, getChapterId, getCourseId, mergeTaskHistory } from './chaoxing-fanya/utils'
import { configSummary } from './chaoxing-fanya/configOptions'
import { describeStartError, describeTask } from './chaoxing-fanya/taskInsights'

import useTaskConfig from './chaoxing-fanya/hooks/useTaskConfig'
import useTaskExecution from './chaoxing-fanya/hooks/useTaskExecution'
import useAuthentication from './chaoxing-fanya/hooks/useAuthentication'

import AttentionPanel from './chaoxing-fanya/components/AttentionPanel'
import LoginSection from './chaoxing-fanya/components/LoginSection'
import CourseListSection from './chaoxing-fanya/components/CourseListSection'
import CoursePortalSection from './chaoxing-fanya/components/CoursePortalSection'
import ConfigSection from './chaoxing-fanya/components/ConfigSection'
import StartBar from './chaoxing-fanya/components/StartBar'
import TaskControlSection from './chaoxing-fanya/components/TaskControlSection'
import TaskHistorySection from './chaoxing-fanya/components/TaskHistorySection'
import LogSection from './chaoxing-fanya/components/LogSection'


const FANYA_TABS = [
  { id: 'courses', label: '选择课程' },
  { id: 'settings', label: '学习配置' },
  { id: 'tasks', label: '执行与日志' },
  { id: 'history', label: '任务记录' },
  { id: 'account', label: '账号' },
]

const splitList = (value) => value.split(',').map((item) => item.trim()).filter(Boolean)

export default function ChaoxingFanya() {
  const [activeTab, setActiveTab] = useWorkspaceTab(FANYA_TABS, 'courses')
  const [selectedCourses, setSelectedCourses] = useState([])
  // courseId -> id of the last chapter to study (inclusive). Absent = whole course.
  const [chapterLimits, setChapterLimits] = useState({})
  const chapterLimitsRef = useRef(chapterLimits)
  useEffect(() => {
    chapterLimitsRef.current = chapterLimits
  }, [chapterLimits])
  const [chapters, setChapters] = useState({})
  // courseId -> { loading, error } for the chapter picker.
  const [chapterStatus, setChapterStatus] = useState({})
  const [expanded, setExpanded] = useState(new Set())
  // Why the last start attempt did not go through: { title, detail, actions }.
  const [startError, setStartError] = useState(null)


  // Shared pollRef lives in parent to break circular dependency between hooks.
  // stopPolling is needed by useAuthentication (for auth error handling)
  // and by useTaskExecution (for polling lifecycle).
  const pollRef = useRef(null)
  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])


  const toast = useToast()

  const taskConfig = useTaskConfig()

  const auth = useAuthentication({ stopPolling })

  // Keep selections valid when a successful login/refresh replaces the course list.
  // A failed refresh leaves auth.courses untouched, so it does not discard choices.
  useEffect(() => {
    const availableCourseIds = new Set(auth.courses.map(getCourseId).filter(Boolean))
    setSelectedCourses((prev) => {
      const next = prev.filter((courseId) => availableCourseIds.has(courseId))
      return next.length === prev.length ? prev : next
    })
    setChapterLimits((prev) => {
      const entries = Object.entries(prev)
      const next = entries.filter(([courseId]) => availableCourseIds.has(courseId))
      return next.length === entries.length ? prev : Object.fromEntries(next)
    })
  }, [auth.courses])

  // Choosing a last chapter implies the course should be studied, so select it.
  const setChapterLimit = useCallback((courseId, chapterId) => {
    setChapterLimits((prev) => {
      const next = { ...prev }
      if (chapterId) next[courseId] = chapterId
      else delete next[courseId]
      return next
    })
    if (chapterId) {
      setSelectedCourses((prev) => (prev.includes(courseId) ? prev : [...prev, courseId]))
    }
  }, [])

  // Surface auth errors / notices through the shared toast and immediately
  // clear the source so the same message can be re-announced if it recurs.
  // Login and course-list failures are already explained inline, so they are
  // not repeated as a toast.
  const {
    error: authError, notice: authNotice, setError: authSetError, setNotice: authSetNotice,
    loginError = '', coursesError = '',
  } = auth
  useEffect(() => {
    if (authError) {
      if (authError !== loginError && authError !== coursesError) toast.error(translateTaskMessage(authError))
      authSetError('')
    }
  }, [authError, authSetError, coursesError, loginError, toast])

  useEffect(() => {
    if (authNotice) {
      toast.success(authNotice)
      authSetNotice('')
    }
  }, [authNotice, authSetNotice, toast])


  const taskExec = useTaskExecution({
    callApi: auth.callApi,
    setError: auth.setError,
    setNotice: auth.setNotice,
    pollRef,
    stopPolling,
  })


  const toggleExpand = useCallback(
    async (course, options = {}) => {
      const courseId = getCourseId(course)
      if (!courseId) return

      const reload = Boolean(options.reload)
      const opening = reload || !expanded.has(courseId)
      if (!reload) {
        setExpanded((prev) => {
          const next = new Set(prev)
          if (next.has(courseId)) next.delete(courseId)
          else next.add(courseId)
          return next
        })
      }

      // Refetch on every open: 已完成 / 待解锁 change as tasks run, and this
      // list is where the user decides how far to study.
      if (!opening) return

      setChapterStatus((prev) => ({ ...prev, [courseId]: { loading: true, error: '' } }))
      try {
        const resp = await auth.callApi(`/course/chapters/${courseId}`)
        if (!resp) {
          setChapterStatus((prev) => ({ ...prev, [courseId]: { loading: false, error: '' } }))
          return
        }
        const nextChapters = resp.chapters || []
        setChapters((prev) => ({ ...prev, [courseId]: nextChapters }))
        setChapterStatus((prev) => ({ ...prev, [courseId]: { loading: false, error: '' } }))
        const chosen = chapterLimitsRef.current[courseId]
        if (chosen && !nextChapters.some((chapter) => getChapterId(chapter) === chosen)) {
          setChapterLimit(courseId, '')
          toast.info('之前选的最后一节已不在这门课里，已改回「全部章节」，请重新选择。')
        }
      } catch (err) {
        const message = translateTaskMessage(err?.message) || '获取章节失败。'
        setChapterStatus((prev) => ({ ...prev, [courseId]: { loading: false, error: message } }))
      }
    },
    [auth, expanded, setChapterLimit, toast]
  )


  const hasCredentials = Boolean(auth.username.trim() && auth.password.trim())
  const statusText = String(taskExec.taskStatus?.status || '').toLowerCase()
  const isRunning = ['started', 'running', 'pending', 'paused', 'cancelling'].includes(statusText)
  const limitCount = Object.keys(chapterLimits).filter((id) => selectedCourses.includes(id)).length


  const startTask = useCallback(async () => {
    auth.setError('')
    auth.setNotice('')
    setStartError(null)

    const availableCourseIds = new Set(auth.courses.map(getCourseId).filter(Boolean))
    const validSelectedCourses = selectedCourses.filter((courseId) => availableCourseIds.has(courseId))


    if (!auth.username.trim() || !auth.password.trim()) {
      setStartError({ title: '还没有登录学习通', detail: '先在「账号」里登录学习通，再开始刷课。', actions: ['relogin'] })
      return
    }
    if (validSelectedCourses.length === 0) {
      setStartError({ title: '还没有选择课程', detail: '在「选择课程」里勾选至少一门课程。', actions: ['courses'] })
      return
    }


    taskExec.setLoading(true)
    taskExec.setLogs([])
    taskExec.setLogCursor(0)
    taskExec.logCursorRef.current = 0


    try {
      const resp = await auth.callApi('/course/start', {
        method: 'POST',
        body: JSON.stringify({
          platform: 'chaoxing',
          username: auth.username.trim(),
          password: auth.password,
          course_ids: validSelectedCourses,
          chapter_limits: Object.fromEntries(
            validSelectedCourses
              .filter((courseId) => chapterLimits[courseId])
              .map((courseId) => [courseId, chapterLimits[courseId]])
          ),
          speed: taskConfig.speed,
          concurrency: taskConfig.concurrency,
          unopened_strategy: taskConfig.unopenedStrategy,
          tiku_config: {
            // Ordered providers → comma-separated `provider` (单题库 or 回退链).
            provider: (Array.isArray(taskConfig.tikuProvider)
              ? taskConfig.tikuProvider
              : [taskConfig.tikuProvider]
            ).join(','),
            token: taskConfig.tikuToken.trim(),
            coverage_threshold: taskConfig.coverageThreshold,
            judge_mapping: {
              correct: splitList(taskConfig.correctOptions),
              wrong: splitList(taskConfig.wrongOptions),
            },
            submit_mode: taskConfig.submitMode
          },
          notify_config:
            taskConfig.notifyService.trim() && taskConfig.notifyUrl.trim()
              ? {
                  service: taskConfig.notifyService.trim(),
                  url: taskConfig.notifyUrl.trim()
                }
              : {}
        })
      })


      if (!resp) return
      if (!resp.task_id) throw new Error('未返回任务 ID，任务未启动。')


      taskExec.setTaskId(resp.task_id)
      taskExec.setTaskStatus(resp)
      taskExec.setTaskHistory((prev) =>
        mergeTaskHistory(
          prev,
          {
            ...resp,
            task_id: resp.task_id,
            status: String(resp.status || 'pending').toLowerCase(),
            updated_at: resp.updated_at || resp.updatedAt || new Date().toISOString()
          },
          true
        )
      )
      taskExec.appendLogs([{ timestamp: new Date().toISOString(), level: 'success', message: '任务已创建，正在准备' }])
      setActiveTab('tasks')
    } catch (err) {
      // Explained next to the start button with a way forward, not as a toast.
      setStartError(describeStartError(err))
    } finally {
      taskExec.setLoading(false)
    }
  }, [
    auth,
    taskExec,
    taskConfig,
    selectedCourses,
    chapterLimits,
    setActiveTab,
  ])


  const showActiveTask = useCallback(async () => {
    setStartError(null)
    setActiveTab('tasks')
    const list = await taskExec.reloadHistory?.()
    const active = Array.isArray(list) ? list.find((task) => RESTORE_STATUSES.has(task.status)) : null
    if (active?.task_id) taskExec.selectTaskFromHistory(active.task_id)
  }, [setActiveTab, taskExec])

  const handleAction = useCallback((action) => {
    if (action === 'relogin') setActiveTab('account')
    else if (action === 'settings') setActiveTab('settings')
    else if (action === 'courses') setActiveTab('courses')
    else if (action === 'tasks') void showActiveTask()
    else if (action === 'retry') {
      if (!hasCredentials) setActiveTab('account')
      else if (selectedCourses.length === 0) setActiveTab('courses')
      else void startTask()
    }
  }, [hasCredentials, selectedCourses.length, setActiveTab, showActiveTask, startTask])

  const handleLogin = useCallback(async (event) => {
    const ok = await auth.handleLogin(event)
    if (ok) {
      setStartError(null)
      setActiveTab('courses')
    }
  }, [auth, setActiveTab])

  const view = useMemo(() => describeTask(taskExec.taskStatus, taskExec.logs), [taskExec.taskStatus, taskExec.logs])

  const startBar = (props = {}) => (
    <StartBar
      selectedCount={selectedCourses.length}
      limitCount={limitCount}
      summary={configSummary(taskConfig)}
      loading={taskExec.loading}
      isRunning={isRunning}
      canStart={hasCredentials}
      blockedReason={hasCredentials ? '' : '先在「账号」里登录学习通。'}
      startError={startError}
      onStart={startTask}
      onAction={handleAction}
      {...props}
    />
  )

  const loginSection = (
    <LoginSection
      username={auth.username}
      setUsername={auth.setUsername}
      password={auth.password}
      setPassword={auth.setPassword}
      loginLoading={auth.loginLoading}
      handleLogin={handleLogin}
      loginError={loginError}
    />
  )

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="学习通"
        title="课程学习"
        actions={(
          <>
            {isRunning && activeTab !== 'tasks' && (
              <button type="button" onClick={() => setActiveTab('tasks')} className="min-h-[44px] rounded-full bg-primary/10 px-4 text-sm font-semibold text-primary">
                查看运行中的任务
              </button>
            )}
            <AccountChip ready={auth.loggedIn} account={auth.username} onClick={() => setActiveTab('account')} />
          </>
        )}
      >
        <WorkspaceTabs id="fanya" label="学习通课程工作区" tabs={FANYA_TABS} activeTab={activeTab} onChange={setActiveTab} />
      </PageHeader>

      {activeTab === 'courses' && (
        <section id="fanya-panel-courses" role="tabpanel" aria-labelledby="fanya-tab-courses" tabIndex="0" className="space-y-4">
          {auth.courses.length === 0 ? (
            auth.loggedIn ? (
              auth.coursesLoading ? (
                <p role="status" className={`${CARD} flex items-center gap-2 text-sm text-text-muted`}>
                  <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />正在获取课程…
                </p>
              ) : coursesError ? (
                <AttentionPanel
                  id="fanya-courses-error"
                  role="alert"
                  attention={{ tone: 'danger', title: '课程没有加载出来', summary: `${translateTaskMessage(coursesError)}。可以重试；如果提示登录失效，请重新登录学习通。`, actions: ['retry', 'relogin'] }}
                  labels={{ retry: '重新获取课程' }}
                  onAction={(action) => (action === 'retry' ? void auth.loadCourses() : setActiveTab('account'))}
                />
              ) : (
                <EmptyState
                  icon={BookOpen}
                  title="这个账号暂无课程"
                  hint="在学习通 App 里加入课程后，回来点「重新获取课程」。"
                  action={(
                    <button type="button" onClick={auth.loadCourses} disabled={auth.loginLoading} className="clay-button-secondary min-h-[44px] gap-1.5 px-4 text-sm">
                      <RefreshCw className="h-4 w-4" aria-hidden="true" />重新获取课程
                    </button>
                  )}
                />
              )
            ) : (
              <div className="max-w-2xl">{loginSection}</div>
            )
          ) : (
            <>
              <CourseListSection
                courses={auth.courses}
                selectedCourses={selectedCourses}
                setSelectedCourses={setSelectedCourses}
                chapters={chapters}
                chapterStatus={chapterStatus}
                expanded={expanded}
                toggleExpand={toggleExpand}
                loadCourses={auth.loadCourses}
                chapterLimits={chapterLimits}
                setChapterLimit={setChapterLimit}
                loadError={coursesError ? translateTaskMessage(coursesError) : ''}
              />
              {startBar({ sticky: true, onEditSettings: () => setActiveTab('settings') })}
              <details className={CARD}>
                <summary className="flex min-h-[44px] cursor-pointer items-center font-semibold text-text">查看课程内容（活动、章节、资料、作业…）</summary>
                <div className="mt-4"><CoursePortalSection courses={auth.courses} selectedCourses={selectedCourses} /></div>
              </details>
            </>
          )}
        </section>
      )}

      {activeTab === 'settings' && (
        <section id="fanya-panel-settings" role="tabpanel" aria-labelledby="fanya-tab-settings" tabIndex="0" className="space-y-4">
          <ConfigSection {...taskConfig} />
          {startBar()}
        </section>
      )}

      {activeTab === 'tasks' && (
        <section id="fanya-panel-tasks" role="tabpanel" aria-labelledby="fanya-tab-tasks" tabIndex="0" className="space-y-4">
          {taskExec.taskId ? (
            <>
              <TaskControlSection
                taskId={taskExec.taskId}
                taskStatus={taskExec.taskStatus}
                logs={taskExec.logs}
                view={view}
                statusText={statusText}
                controlTask={taskExec.controlTask}
                controlLoading={taskExec.controlLoading}
                pollError={taskExec.pollError}
                onRefresh={taskExec.refreshTask}
              />
              <AttentionPanel id="fanya-task-attention" attention={view.attention} onAction={handleAction} />
              {!isRunning && startBar({ onEditSettings: () => setActiveTab('settings') })}
              <LogSection logs={taskExec.logs} />
            </>
          ) : taskExec.historyLoading ? (
            <p role="status" className={`${CARD} flex items-center gap-2 text-sm text-text-muted`}>
              <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />正在读取任务…
            </p>
          ) : (
            <>
              <EmptyState
                icon={BookOpen}
                title="还没有开始任务"
                hint={auth.courses.length > 0 ? '选好课程后点「开始刷课」，进度和日志会显示在这里。' : '先登录学习通并选择课程，开始后进度和日志会显示在这里。'}
              />
              {startBar({ onEditSettings: () => setActiveTab('settings') })}
            </>
          )}
        </section>
      )}

      {activeTab === 'history' && (
        <section id="fanya-panel-history" role="tabpanel" aria-labelledby="fanya-tab-history" tabIndex="0">
          <TaskHistorySection
            taskHistory={taskExec.taskHistory}
            taskId={taskExec.taskId}
            loading={taskExec.historyLoading}
            error={taskExec.historyError}
            onRetry={taskExec.reloadHistory}
            onStartNew={() => setActiveTab('courses')}
            selectTaskFromHistory={async (task) => { setActiveTab('tasks'); await taskExec.selectTaskFromHistory(task) }}
          />
        </section>
      )}

      {activeTab === 'account' && (
        <section id="fanya-panel-account" role="tabpanel" aria-labelledby="fanya-tab-account" tabIndex="0" className="max-w-2xl space-y-4">
          {loginSection}
          {auth.loggedIn && (
            <div className={`${CARD} flex flex-wrap items-center justify-between gap-3`}>
              <p className="text-sm text-text-muted">已加载 {auth.courses.length} 门课程</p>
              <button type="button" onClick={() => setActiveTab('courses')} className="clay-button-secondary min-h-[44px] px-4 text-sm">前往选择课程</button>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
