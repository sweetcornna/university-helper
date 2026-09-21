import { useCallback, useEffect, useRef, useState } from 'react'

import { useToast } from '../components'

import { CARD, getCourseId, mergeTaskHistory } from './chaoxing-fanya/utils'


import useTaskConfig from './chaoxing-fanya/hooks/useTaskConfig'
import useTaskPreferences from './chaoxing-fanya/hooks/useTaskPreferences'
import useTaskExecution from './chaoxing-fanya/hooks/useTaskExecution'
import useAuthentication from './chaoxing-fanya/hooks/useAuthentication'


import LoginSection from './chaoxing-fanya/components/LoginSection'
import OneClickSection from './chaoxing-fanya/components/OneClickSection'
import CourseListSection from './chaoxing-fanya/components/CourseListSection'
import CoursePortalSection from './chaoxing-fanya/components/CoursePortalSection'
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


  const toast = useToast()

  const taskConfig = useTaskConfig()

  // Server-held task settings (answer-bank credentials included). The one-click
  // run reads these to say what it will actually do before it starts.
  const prefs = useTaskPreferences()


  const auth = useAuthentication({ stopPolling })

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
    [auth, chapters]
  )


  const startTask = useCallback(async () => {
    auth.setError('')
    auth.setNotice('')


    // The username is always required: the backend binds the reused cookie jar
    // to it, so without it a task could adopt a session for another account.
    // The password is only needed when there is NO server-held session — the
    // backend accepts an empty one once a session bound to this account exists
    // (learning_manager._run_task_worker). Demanding it unconditionally here
    // would make the persisted 7-day login pointless at the moment it matters.
    if (!auth.username.trim() || (auth.sessionStatus !== 'active' && !auth.password.trim())) {
      auth.requireCredentials()
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
            // Ordered providers → comma-separated `provider` (单题库 or 回退链).
            provider: (Array.isArray(taskConfig.tikuProvider)
              ? taskConfig.tikuProvider
              : [taskConfig.tikuProvider]
            ).filter(Boolean).join(','),
            token: taskConfig.tikuToken.trim(),
            // Always send AI fields; backend disables AI provider when empty.
            endpoint: (taskConfig.aiEndpoint || '').trim(),
            key: (taskConfig.aiKey || '').trim(),
            model: (taskConfig.aiModel || '').trim(),
            // SiliconFlow can reuse the same key field / token as fallback.
            siliconflow_key: (taskConfig.aiKey || taskConfig.tikuToken || '').trim(),
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
    <div>
      <div className="space-y-6">
        <section className={CARD}>
          <h1 className="text-3xl font-bold text-text">超星学习通自动刷课</h1>
          <p className="mt-2 text-sm text-text/70">支持离开页面后恢复任务状态、日志与历史任务查看。</p>
        </section>


        <LoginSection
          username={auth.username}
          setUsername={auth.setUsername}
          password={auth.password}
          setPassword={auth.setPassword}
          loginLoading={auth.loginLoading}
          handleLogin={auth.handleLogin}
          sessionStatus={auth.sessionStatus}
          sessionUsername={auth.sessionUsername}
          sessionExpiresAt={auth.sessionExpiresAt}
          switchAccount={auth.switchAccount}
          switchLoading={auth.switchLoading}
          credentialsRequired={auth.credentialsRequired}
          qrRequest={auth.callChaoxingApi}
          onQrSuccess={auth.handleQrSuccess}
        />

        {auth.authenticated && (
          <>
            <OneClickSection
              courses={auth.courses}
              selectedCourses={selectedCourses}
              setSelectedCourses={setSelectedCourses}
              startTask={startTask}
              loading={taskExec.loading}
              authenticated={auth.authenticated}
              preferences={prefs.preferences}
              hasAnswerBank={prefs.hasAnswerBank}
              preferencesLoading={prefs.loading}
              preferencesError={prefs.loadError}
            />

            <CourseListSection
              courses={auth.courses}
              selectedCourses={selectedCourses}
              setSelectedCourses={setSelectedCourses}
              chapters={chapters}
              expanded={expanded}
              toggleExpand={toggleExpand}
              loadCourses={auth.loadCourses}
            />

            <CoursePortalSection
              courses={auth.courses}
              selectedCourses={selectedCourses}
              setError={auth.setError}
              setNotice={auth.setNotice}
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
