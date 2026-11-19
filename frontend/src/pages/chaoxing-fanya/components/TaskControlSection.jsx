import { Pause, Play, RefreshCw, Square, WifiOff } from 'lucide-react'

import { ProgressMeter, StateNotice, StatusBadge } from '../../../components'
import { CARD, DONE_STATUSES, formatTaskTime, toNum } from '../utils'
import { describeTask } from '../taskInsights'

const ACCENT = {
  info: 'border-l-primary',
  success: 'border-l-success',
  danger: 'border-l-danger',
  warning: 'border-l-warning',
  muted: 'border-l-border',
}

const percentOf = (done, total) => (total > 0 ? Math.min(100, Math.max(0, (done / total) * 100)) : 0)

const clock = (seconds) => {
  const value = Math.max(0, Math.round(toNum(seconds)))
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`
}

// Status-first view of the selected task: Chinese status, one-line headline,
// progress, and the controls that make sense right now.
export default function TaskControlSection({
  taskId, taskStatus, logs = [], view: precomputed, controlTask, controlLoading = {}, pollError = null, onRefresh,
}) {
  const view = precomputed || describeTask(taskStatus, logs)
  const status = view.status
  const progress = taskStatus?.progress || {}
  const totalChapters = toNum(progress.total_chapters)
  const doneChapters = toNum(progress.completed_chapters)
  const totalCourses = toNum(progress.total)
  const doneCourses = toNum(progress.completed)
  const failedCourses = toNum(progress.failed)
  const video = progress.video_progress && typeof progress.video_progress === 'object' ? progress.video_progress : null
  const showVideo = Boolean(video?.name) && (status === 'running' || status === 'paused')
  const done = DONE_STATUSES.has(status)
  const updatedAt = taskStatus?.updated_at || taskStatus?.updatedAt

  return (
    <section aria-labelledby="fanya-task-headline" className={`${CARD} border-l-4 ${ACCENT[view.tone] || ACCENT.muted}`}>
      <p className="sr-only" role="status" aria-live="polite">{`任务状态：${view.label}。${view.headline}`}</p>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <StatusBadge status={status} label={view.label} tone={view.tone} />
          <h2 id="fanya-task-headline" className="mt-2 break-words font-display text-xl font-bold text-text">{view.headline}</h2>
          {view.detail && <p className="mt-1 break-words text-sm text-text-muted">{view.detail}</p>}
        </div>
        {updatedAt && <p className="text-xs text-text-muted">更新于 {formatTaskTime(updatedAt)}</p>}
      </div>

      {pollError && (
        <StateNotice
          kind="warning"
          icon={WifiOff}
          role="status"
          className="mt-4"
          action={!pollError.missing && onRefresh && (
            <button type="button" onClick={onRefresh} className="ui-btn-secondary min-h-[44px]">
              <RefreshCw className="h-4 w-4" aria-hidden="true" />立即刷新
            </button>
          )}
        >
          {pollError.missing
            ? '任务记录可能已过期。以下是上次读取的状态。'
            : `暂时读不到最新进度，正在自动重试。${pollError.message ? `（${pollError.message}）` : ''}`}
        </StateNotice>
      )}

      {(totalChapters > 0 || totalCourses > 0) && (
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <ProgressMeter
            label="章节进度"
            detail={`${doneChapters}/${totalChapters}`}
            value={percentOf(doneChapters, totalChapters)}
            known={totalChapters > 0}
          />
          <ProgressMeter
            label="课程进度"
            detail={`${doneCourses}/${totalCourses}${failedCourses > 0 ? `（${failedCourses} 门未完成）` : ''}`}
            value={percentOf(doneCourses, totalCourses)}
            tone="success"
            known={totalCourses > 0}
          />
        </div>
      )}

      {showVideo && (
        <div className="mt-4 ui-panel p-3">
          <ProgressMeter
            label={`当前视频：${video.name}`}
            detail={`${clock(video.current)} / ${clock(video.duration)}`}
            value={percentOf(toNum(video.current), toNum(video.duration))}
            known={toNum(video.duration) > 0}
          />
        </div>
      )}

      {taskId && !done && (
        <div className="mt-5 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => { void controlTask('pause') }}
            disabled={status !== 'running' || Boolean(controlLoading?.pause)}
            className="ui-btn-secondary min-h-[44px]"
          >
            <Pause className="h-4 w-4" aria-hidden="true" />暂停
          </button>
          <button
            type="button"
            onClick={() => { void controlTask('resume') }}
            disabled={status !== 'paused' || Boolean(controlLoading?.resume)}
            className="ui-btn-secondary min-h-[44px]"
          >
            <Play className="h-4 w-4" aria-hidden="true" />继续
          </button>
          <button
            type="button"
            onClick={() => {
              if (window.confirm('确定要停止当前刷课任务吗？')) void controlTask('stop')
            }}
            disabled={['cancelling', 'stopping'].includes(status) || Boolean(controlLoading?.stop)}
            className="ui-btn-danger min-h-[44px]"
          >
            <Square className="h-4 w-4" aria-hidden="true" />停止
          </button>
        </div>
      )}

      {taskId && (
        <p className="mt-4 break-all text-xs text-text-muted">
          任务编号 <span className="font-code">{taskId}</span>
        </p>
      )}
    </section>
  )
}
