import { useCallback, useRef, useState } from 'react'


import { CARD, getCourseId, mergeTaskHistory, toNum } from './chaoxing-fanya/utils'


import useTaskConfig from './chaoxing-fanya/hooks/useTaskConfig'
import useTaskExecution from './chaoxing-fanya/hooks/useTaskExecution'
import useAuthentication from './chaoxing-fanya/hooks/useAuthentication'


import LoginSection from './chaoxing-fanya/components/LoginSection'
import CourseListSection from './chaoxing-fanya/components/CourseListSection'
import ConfigSection from './chaoxing-fanya/components/ConfigSection'
import TaskControlSection from './chaoxing-fanya/components/TaskControlSection'
import TaskHistorySection from './chaoxing-fanya/components/TaskHistorySection'
import LogSection from './chaoxing-fanya/components/LogSection'


export default function ChaoxingFanya() {


  const [selectedCourses, setSelectedCourses] = useState([])
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


  const taskConfig = useTaskConfig()


  const auth = useAuthentication({ stopPolling })


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


      setExpanded((prev) => {
        const next = new Set(prev)
        if (next.has(courseId)) next.delete(courseId)
        else next.add(courseId)
        return next
      })


      if (chapters[courseId]) return


      try {
        const resp = await auth.callApi(`/course/chapters/${courseId}`)
        if (!resp) return
        setChapters((prev) => ({ ...prev, [courseId]: resp.chapters || [] }))
      } catch (err) {
        auth.setError(err?.message || '获取章节失败。')
      }
    },
    [auth.callApi, chapters, auth.setError]
  )


  const startTask = useCallback(async () => {
    auth.setError('')
    auth.setNotice('')


    if (!auth.username.trim() || !auth.password.trim()) {
      auth.setError('请先填写账号和密码。')
      return
    }
    if (selectedCourses.length === 0) {
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
          course_ids: selectedCourses,
          speed: taskConfig.speed,
          concurrency: taskConfig.concurrency,
          unopened_strategy: taskConfig.unopenedStrategy,
          tiku_config: {
            provider: taskConfig.tikuProvider,
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
      if (!resp.task_id) throw new Error('后端未返回任务 ID。')


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
    } catch (err) {
      taskExec.setLoading(false)
      auth.setError(err?.message || '启动任务失败。')
    }
  }, [
    auth,
    taskExec,
    taskConfig,
    selectedCourses,
  ])


  const statusText = String(taskExec.taskStatus?.status || '').toLowerCase()
  const isRunning = ['started', 'running', 'pending', 'paused', 'cancelling'].includes(statusText)


  return (
    <div className="min-h-screen bg-[#F8FAFC] p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        <section className={CARD}>
          <h1 className="text-3xl font-bold text-slate-900">超星学习通自动刷课</h1>
          <p className="mt-2 text-sm text-slate-600">支持离开页面后恢复任务状态、日志与历史任务查看。</p>
        </section>


        {auth.error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{auth.error}</div>}
        {auth.notice && <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{auth.notice}</div>}


        {auth.courses.length === 0 ? (
          <LoginSection
            username={auth.username}
            setUsername={auth.setUsername}
            password={auth.password}
            setPassword={auth.setPassword}
            loginLoading={auth.loginLoading}
            handleLogin={auth.handleLogin}
          />
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
            />


            <ConfigSection {...taskConfig} />


            <TaskControlSection
              taskId={taskExec.taskId}
              taskStatus={taskExec.taskStatus}
              loading={taskExec.loading}
              isRunning={isRunning}
              statusText={statusText}
              startTask={startTask}
              controlTask={taskExec.controlTask}
            />


            <TaskHistorySection
              taskHistory={taskExec.taskHistory}
              taskId={taskExec.taskId}
              selectTaskFromHistory={taskExec.selectTaskFromHistory}
            />
          </>
        )}


        <LogSection logs={taskExec.logs} />
      </div>
    </div>
  )
}
