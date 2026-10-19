import { useCallback, useEffect, useRef, useState } from 'react'

import { AccountChip, PageHeader, useToast } from '../components'
import WorkspaceTabs from '../components/WorkspaceTabs'
import useWorkspaceTab from '../components/useWorkspaceTab'

import { CARD, getChapterId, getCourseId, mergeTaskHistory } from './chaoxing-fanya/utils'


import useTaskConfig from './chaoxing-fanya/hooks/useTaskConfig'
import useTaskExecution from './chaoxing-fanya/hooks/useTaskExecution'
import useAuthentication from './chaoxing-fanya/hooks/useAuthentication'


import LoginSection from './chaoxing-fanya/components/LoginSection'
import CourseListSection from './chaoxing-fanya/components/CourseListSection'
import CoursePortalSection from './chaoxing-fanya/components/CoursePortalSection'
import ConfigSection from './chaoxing-fanya/components/ConfigSection'
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
  const [expanded, setExpanded] = useState(new Set())


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
  const { error: authError, notice: authNotice, setError: authSetError, setNotice: authSetNotice } =
    auth
  useEffect(() => {
    if (authError) {
      toast.error(authError)
      authSetError('')
    }
  }, [authError, authSetError, toast])

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
    async (course) => {
      const courseId = getCourseId(course)
      if (!courseId) return


      const opening = !expanded.has(courseId)
      setExpanded((prev) => {
        const next = new Set(prev)
        if (next.has(courseId)) next.delete(courseId)
        else next.add(courseId)
        return next
      })


      // Refetch on every open: 已完成 / 待解锁 change as tasks run, and this
      // list is where the user decides how far to study.
      if (!opening) return


      try {
        const resp = await auth.callApi(`/course/chapters/${courseId}`)
        if (!resp) return
        const nextChapters = resp.chapters || []
        setChapters((prev) => ({ ...prev, [courseId]: nextChapters }))
        const chosen = chapterLimitsRef.current[courseId]
        if (chosen && !nextChapters.some((chapter) => getChapterId(chapter) === chosen)) {
          setChapterLimit(courseId, '')
          toast.info('之前选的最后一节已不在这门课里，已改回「全部章节」，请重新选择。')
        }
      } catch (err) {
        auth.setError(err?.message || '获取章节失败。')
      }
    },
    [auth, expanded, setChapterLimit, toast]
  )


  const startTask = useCallback(async () => {
    auth.setError('')
    auth.setNotice('')

    const availableCourseIds = new Set(auth.courses.map(getCourseId).filter(Boolean))
    const validSelectedCourses = selectedCourses.filter((courseId) => availableCourseIds.has(courseId))


    if (!auth.username.trim() || !auth.password.trim()) {
      auth.setError('请先填写账号和密码。')
      return
    }
    if (validSelectedCourses.length === 0) {
      auth.setError('请至少选择一门课程。')
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
              correct: taskConfig.correctOptions
                .split(',')
                .map((item) => item.trim())
                .filter(Boolean),
              wrong: taskConfig.wrongOptions
                .split(',')
                .map((item) => item.trim())
                .filter(Boolean)
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
      taskExec.appendLogs([{ timestamp: new Date().toISOString(), level: 'success', message: `任务已创建：${resp.task_id}` }])
      setActiveTab('tasks')
    } catch (err) {
      auth.setError(err?.message || '启动任务失败。')
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


  const statusText = String(taskExec.taskStatus?.status || '').toLowerCase()
  const isRunning = ['started', 'running', 'pending', 'paused', 'cancelling'].includes(statusText)


  const loginSection = (
    <LoginSection
      username={auth.username}
      setUsername={auth.setUsername}
      password={auth.password}
      setPassword={auth.setPassword}
      loginLoading={auth.loginLoading}
      handleLogin={auth.handleLogin}
    />
  )

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="学习通"
        title="课程学习"
        actions={(
          <>
            {isRunning && (
              <button type="button" onClick={() => setActiveTab('tasks')} className="min-h-[40px] rounded-full bg-primary/10 px-4 text-sm font-semibold text-primary">
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
              <div className={`${CARD} flex flex-wrap items-center justify-between gap-3`}>
                <p role="status" className="text-sm text-text-muted">{auth.coursesLoading ? '正在获取课程...' : '这个账号暂无课程；在学习通加入课程后可重新获取。'}</p>
                <button type="button" onClick={auth.loadCourses} disabled={auth.coursesLoading || auth.loginLoading} className="min-h-[44px] rounded-xl border border-border px-4 text-sm font-semibold disabled:opacity-60">重新获取课程</button>
              </div>
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
                expanded={expanded}
                toggleExpand={toggleExpand}
                loadCourses={auth.loadCourses}
                chapterLimits={chapterLimits}
                setChapterLimit={setChapterLimit}
              />
              <div className={`${CARD} flex flex-wrap items-center justify-between gap-4`}>
                <p className="text-sm text-text-muted">已选 <strong className="text-text">{selectedCourses.length}</strong> 门课程</p>
                <button type="button" onClick={() => setActiveTab('settings')} disabled={selectedCourses.length === 0} className="min-h-[44px] rounded-xl bg-primary px-5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50">下一步：学习配置</button>
              </div>
              <details className={CARD}>
                <summary className="cursor-pointer font-semibold text-text">查看课程内容（活动、章节、资料、作业…）</summary>
                <div className="mt-4"><CoursePortalSection courses={auth.courses} selectedCourses={selectedCourses} /></div>
              </details>
            </>
          )}
        </section>
      )}

      {activeTab === 'settings' && (
        <section id="fanya-panel-settings" role="tabpanel" aria-labelledby="fanya-tab-settings" tabIndex="0" className="space-y-4">
          <ConfigSection {...taskConfig} />
          <div className={`${CARD} flex flex-wrap items-center justify-between gap-3`}>
            <p className="text-sm text-text-muted">配置自动保存在本机 · 已选 {selectedCourses.length} 门课程</p>
            <button type="button" onClick={() => setActiveTab('tasks')} className="min-h-[44px] rounded-xl bg-primary px-5 text-sm font-semibold text-white">下一步：确认并执行</button>
          </div>
        </section>
      )}

      {activeTab === 'tasks' && (
        <section id="fanya-panel-tasks" role="tabpanel" aria-labelledby="fanya-tab-tasks" tabIndex="0" className="space-y-4">
          <div className={`${CARD} flex flex-wrap items-center justify-between gap-3`}>
            <div>
              <h2 className="font-semibold text-text">本次学习任务</h2>
              <p className="mt-1 text-sm text-text-muted">{selectedCourses.length} 门课程 · {taskConfig.speed.toFixed(1)} 倍速 · {taskConfig.concurrency} 个并发章节 · {Object.keys(chapterLimits).filter((id) => selectedCourses.includes(id)).length} 门设了章节终点</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {(!auth.username.trim() || !auth.password.trim())
                ? <button type="button" onClick={() => setActiveTab('account')} className="min-h-[44px] rounded-xl border border-border px-4 text-sm font-semibold">先登录学习通</button>
                : <button type="button" onClick={() => setActiveTab('courses')} className="min-h-[44px] rounded-xl border border-border px-4 text-sm font-semibold">修改课程</button>}
            </div>
          </div>
          <TaskControlSection taskId={taskExec.taskId} taskStatus={taskExec.taskStatus} loading={taskExec.loading} controlLoading={taskExec.controlLoading} isRunning={isRunning} statusText={statusText} startTask={startTask} controlTask={taskExec.controlTask} />
          <LogSection logs={taskExec.logs} />
        </section>
      )}

      {activeTab === 'history' && (
        <section id="fanya-panel-history" role="tabpanel" aria-labelledby="fanya-tab-history" tabIndex="0">
          <TaskHistorySection taskHistory={taskExec.taskHistory} taskId={taskExec.taskId} selectTaskFromHistory={async (task) => { setActiveTab('tasks'); await taskExec.selectTaskFromHistory(task) }} />
        </section>
      )}

      {activeTab === 'account' && (
        <section id="fanya-panel-account" role="tabpanel" aria-labelledby="fanya-tab-account" tabIndex="0" className="max-w-2xl space-y-4">
          {loginSection}
          {auth.loggedIn && (
            <div className={`${CARD} flex flex-wrap items-center justify-between gap-3`}>
              <p className="text-sm text-text-muted">已加载 {auth.courses.length} 门课程</p>
              <button type="button" onClick={() => setActiveTab('courses')} className="min-h-[44px] rounded-xl border border-border px-4 text-sm font-semibold">前往选择课程</button>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
