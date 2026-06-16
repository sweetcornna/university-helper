 
import { Camera, MapPin, QrCode, CheckSquare, Clock, ExternalLink } from 'lucide-react'
import { RefreshCw } from 'lucide-react'

import { Button } from '../../../components'

import { safeHref } from '../../../utils/safeUrl'

import { GLASS_PANEL_CLASS } from '../utils'

const getSignTypeIcon = (type) => {
  switch (type) {
    case 'photo': return <Camera className="h-5 w-5" />
    case 'location': return <MapPin className="h-5 w-5" />
    case 'qrcode': return <QrCode className="h-5 w-5" />
    default: return <CheckSquare className="h-5 w-5" />
  }
}

export default function TasksTab({ signinTasks, fetchSigninTasks, openBackgroundTask, executeSignin, executeClassSignin }) {
  return (
    <div className="mt-6 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-bold text-text">签到任务列表</h3>
        <Button
          type="button"
          variant="secondary"
          className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200"
          onClick={fetchSigninTasks}
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>
      {signinTasks.length === 0 ? (
        <p className="text-center text-text/70 py-8">暂无签到任务</p>
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
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3 flex-1">
                  <div className="mt-1">{getSignTypeIcon(taskType)}</div>
                  <div className="flex-1">
                    <h4 className="font-medium text-text">{title}</h4>
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
                        学习通远程提交接口
                      </a>
                    )}
                  </div>
                </div>
                <Button
                  type="button"
                  disabled={isBackgroundTask && !backgroundTaskId}
                  className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200"
                  onClick={(event) => {
                    event.stopPropagation()
                    if (isBackgroundTask) {
                      if (backgroundTaskId) {
                        void openBackgroundTask(backgroundTaskId)
                      }
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
                  {isBackgroundTask ? '查看详情' : '执行签到'}
                </Button>
              </div>
            </div>
            )})}
        </div>
      )}
    </div>
  )
}
