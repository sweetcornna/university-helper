import { Camera, MapPin, QrCode, CheckSquare, Clock, ExternalLink, RefreshCw } from 'lucide-react'

import { Button } from '../../../components'

import { safeHref } from '../../../utils/safeUrl'

import { GLASS_CARD_CLASS, GLASS_PANEL_CLASS } from '../utils'

const getSignTypeIcon = (type) => {
  switch (type) {
    case 'photo': return <Camera className="h-5 w-5" />
    case 'location': return <MapPin className="h-5 w-5" />
    case 'qrcode': return <QrCode className="h-5 w-5" />
    default: return <CheckSquare className="h-5 w-5" />
  }
}

export default function TasksTab({ signinTasks, fetchSigninTasks, openBackgroundTask, executeSignin, executeClassSignin, onApplyTask, onOpenAccount, accountReady = true, refreshing = false, error = '' }) {
  return (
    <div className={`${GLASS_CARD_CLASS} space-y-4`}>
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-bold text-text">签到任务</h2>
        <Button
          type="button"
          variant="secondary"
          size="icon"
          aria-label="刷新签到任务"
          title="刷新签到任务"
          onClick={fetchSigninTasks}
          disabled={refreshing}
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} aria-hidden="true" />
        </Button>
      </div>
      {error && <p role="alert" className="rounded-xl bg-danger-surface p-3 text-sm text-danger">{error}</p>}
      {signinTasks.length === 0 ? (
        !error && (
          <div role="status" className="flex flex-col items-center gap-3 py-6 text-center text-sm text-text-muted">
            <p>{refreshing ? '正在检测签到...' : accountReady ? '暂无进行中的签到' : '验证学习通账号后即可检测签到'}</p>
            {!refreshing && !accountReady && onOpenAccount && (
              <Button type="button" variant="secondary" size="sm" onClick={onOpenAccount}>去验证账号</Button>
            )}
          </div>
        )
      ) : (
        <div className="space-y-3">
          {signinTasks.map((task, idx) => {
            const isBackgroundTask = task?.actionable === false || task?.source === 'background'
            const backgroundTaskId = String(task?.taskId || task?.task_id || '').trim()
            const taskType = String(task?.type || 'normal')
            const taskTypeLabel = String(task?.typeLabel || taskType || 'normal')
            const taskMessage = String(task?.message || '')
            const taskStatusValue = String(task?.status || '').toLowerCase()
            const isClassTask = String(task?.subjectType || '').toLowerCase() === 'class'
            const title = isClassTask
              ? (task.className || task.courseName || (isBackgroundTask ? '班级后台签到任务' : '班级签到任务'))
              : (task.courseName || (isBackgroundTask ? '后台签到任务' : '待处理签到任务'))
            // Sanitize Chaoxing-derived submit URL to http(s) only before it is
            // bound to an <a href>, blocking javascript:/data: DOM XSS (F60).
            const remoteSubmitUrl = safeHref(task?.remoteEndpoints?.endpoints?.submitSign?.url)
            return (
            <div
              key={idx}
              className={`${GLASS_PANEL_CLASS} ${isBackgroundTask && backgroundTaskId ? 'cursor-pointer transition-all duration-200 hover:border-primary/40' : ''}`}
              role={isBackgroundTask && backgroundTaskId ? 'button' : undefined}
              tabIndex={isBackgroundTask && backgroundTaskId ? 0 : undefined}
              onClick={() => {
                if (isBackgroundTask && backgroundTaskId) {
                  void openBackgroundTask(backgroundTaskId)
                }
              }}
              onKeyDown={(event) => {
                if (!isBackgroundTask || !backgroundTaskId) return
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  void openBackgroundTask(backgroundTaskId)
                }
              }}
            >
              <div className="flex flex-col items-start justify-between gap-4 sm:flex-row">
                <div className="flex min-w-0 items-start gap-3 flex-1">
                  <div className="mt-1">{getSignTypeIcon(taskType)}</div>
                  <div className="min-w-0 flex-1">
                    <h3 className="break-words font-medium text-text">{title}</h3>
                    {isClassTask && task.courseName && task.courseName !== title && (
                      <p className="text-sm text-text/70 mt-1">所属课程：{task.courseName}</p>
                    )}
                    <p className="text-sm text-text/70 mt-1">签到类型：{taskTypeLabel}</p>
                    {taskMessage && (
                      <p className="text-sm text-text/70 mt-1">{taskMessage}</p>
                    )}
                    {isBackgroundTask && taskStatusValue && (
                      <p className="text-sm text-text/70 mt-1">任务状态：{taskStatusValue}</p>
                    )}
                    {task.deadline && (
                      <p className="text-sm text-text/70 flex items-center gap-1 mt-1">
                        <Clock className="h-3 w-3" />
                        截止时间：{new Date(task.deadline).toLocaleString()}
                      </p>
                    )}
                    {remoteSubmitUrl && (
                      <a
                        className="mt-2 inline-flex items-center gap-1 break-all text-xs text-primary hover:underline"
                        href={remoteSubmitUrl}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                        在学习通提交
                      </a>
                    )}
                  </div>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={isBackgroundTask && !backgroundTaskId}
                  className="shrink-0"
                  onClick={(event) => {
                    event.stopPropagation()
                    if (isBackgroundTask) {
                      if (backgroundTaskId) {
                        void openBackgroundTask(backgroundTaskId)
                      }
                      return
                    }
                    if (onApplyTask) {
                      onApplyTask(task)
                      return
                    }
                    if (isClassTask && task.classId && executeClassSignin) {
                      void executeClassSignin({
                        id: task.courseSelector || task.courseId || task.classId,
                        classId: String(task.classId),
                        courseId: String(task.rawCourseId || ''),
                        courseSelector: String(task.courseSelector || task.courseId || ''),
                        name: title,
                      }, taskType)
                      return
                    }
                    void executeSignin(task.courseId, taskType)
                  }}
                >
                  {isBackgroundTask ? '查看详情' : onApplyTask ? '填写并签到' : '执行签到'}
                </Button>
              </div>
            </div>
            )})}
        </div>
      )}
    </div>
  )
}
