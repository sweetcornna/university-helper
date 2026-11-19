import { Camera, MapPin, QrCode, CheckSquare, Clock, ExternalLink, HelpCircle, KeyRound, Hand, RefreshCw } from 'lucide-react'

import { Button, StateNotice, StatusBadge } from '../../../components'

import { GLASS_CARD_CLASS, SIGN_TYPE_META } from '../utils'
import { backgroundTaskBadge, signinPlatformUrl, signinTaskId, signinTaskKind } from '../taskPresentation'

const TYPE_ICONS = {
  photo: Camera,
  location: MapPin,
  qrcode: QrCode,
  gesture: Hand,
  code: KeyRound,
  normal: CheckSquare,
}

export default function TasksTab({ signinTasks, fetchSigninTasks, openBackgroundTask, executeSignin, executeClassSignin, onApplyTask, onOpenAccount, accountReady = true, refreshing = false, error = '' }) {
  return (
    <section className={`${GLASS_CARD_CLASS} space-y-4`} aria-labelledby="cx-pending-heading">
      <div className="flex items-center justify-between gap-3">
        <h2 id="cx-pending-heading" className="font-display text-base font-bold text-text">签到任务</h2>
        <Button
          type="button"
          variant="secondary"
          size="icon"
          aria-label="刷新签到任务"
          title="刷新签到任务"
          onClick={fetchSigninTasks}
          disabled={refreshing}
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? 'motion-safe:animate-spin' : ''}`} aria-hidden="true" />
        </Button>
      </div>
      {error && <p role="alert" className="rounded-lg border border-danger/35 bg-danger-surface px-3 py-2.5 text-sm text-danger">{error}</p>}
      {signinTasks.length === 0 ? (
        !error && (
          <StateNotice
            kind={refreshing ? 'loading' : accountReady ? 'empty' : 'disabled'}
            role="status"
            action={!refreshing && !accountReady && onOpenAccount ? (
              <Button type="button" variant="secondary" size="sm" onClick={onOpenAccount}>去验证账号</Button>
            ) : null}
          >
            <p>{refreshing ? '正在检测签到...' : accountReady ? '暂无进行中的签到' : '先验证学习通账号'}</p>
          </StateNotice>
        )
      ) : (
        <ul className="grid gap-3 xl:grid-cols-2">
          {signinTasks.map((task, idx) => {
            const kind = signinTaskKind(task)
            const isBackgroundTask = kind === 'background' || kind === 'history'
            const backgroundTaskId = signinTaskId(task)
            const taskType = String(task?.type || 'normal')
            const taskTypeLabel = String(SIGN_TYPE_META[taskType]?.label || task?.typeLabel || taskType)
            const taskMessage = String(task?.message || '')
            const taskStatusValue = String(task?.status || '').toLowerCase()
            const isClassTask = String(task?.subjectType || '').toLowerCase() === 'class'
            const title = isClassTask
              ? (task.className || task.courseName || (isBackgroundTask ? '班级后台签到任务' : '班级签到任务'))
              : (task.courseName || (isBackgroundTask ? '后台签到任务' : '待处理签到任务'))
            // Only the official confirmation page is ever linked (https on
            // chaoxing.com); write endpoints and javascript:/data: are dropped (F60).
            const platformUrl = isBackgroundTask ? '' : signinPlatformUrl(task)
            const badge = kind === 'background' ? backgroundTaskBadge(task) : null
            const TypeIcon = TYPE_ICONS[taskType] || HelpCircle
            return (
              <li
                key={idx}
                className={`spine-signin flex flex-col gap-3 rounded-lg border p-3.5 ${kind === 'guided' ? 'border-warning/40 bg-warning-surface/40' : 'border-border-subtle bg-surface'}`}
              >
                <div className="flex min-w-0 items-start gap-3">
                  <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-md border border-border bg-surface-hover text-text">
                    <TypeIcon className="h-4 w-4" aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <h3 className="break-words text-sm font-semibold text-text">{title}</h3>
                    {isClassTask && task.courseName && task.courseName !== title && (
                      <p className="mt-1 text-xs text-text-muted">所属课程：{task.courseName}</p>
                    )}
                    {task?.name && <p className="mt-1 break-words text-sm text-text">{task.name}</p>}
                    <p className="mt-1 text-xs text-text-muted">签到类型：{taskTypeLabel}</p>
                    {taskMessage && (
                      <p className="mt-1 break-words text-xs text-text-muted">{taskMessage}</p>
                    )}
                    {kind === 'guided' && (
                      <p className="mt-1 text-xs text-warning">{task?.unsupportedReason || '请在学习通完成签到。'}</p>
                    )}
                    {task.deadline && (
                      <p className="mt-1 flex items-center gap-1 text-xs text-text-muted">
                        <Clock className="h-3 w-3" aria-hidden="true" />
                        截止时间：{new Date(task.deadline).toLocaleString()}
                      </p>
                    )}
                  </div>
                  {badge ? (
                    <StatusBadge status={badge.status} label={badge.label} />
                  ) : taskStatusValue ? (
                    <StatusBadge status={taskStatusValue} />
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-2 border-t border-border-subtle pt-3">
                  {kind !== 'guided' && (
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      disabled={isBackgroundTask && !backgroundTaskId}
                      onClick={() => {
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
                  )}
                  {platformUrl && (
                    <a
                      className={kind === 'guided' ? 'ui-btn-primary ui-btn-sm' : 'ui-btn-ghost ui-btn-sm'}
                      href={platformUrl}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                      在学习通打开
                    </a>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
