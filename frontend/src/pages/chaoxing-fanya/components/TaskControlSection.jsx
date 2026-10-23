import { Pause, Play, RefreshCw, Square, WifiOff } from 'lucide-react'

import { StatusBadge } from '../../../components'
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

function ProgressRow({ label, value, percent, barClass }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-text-muted">{label}</span>
        <span className="font-semibold tabular-nums text-text">{value}</span>
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(percent)}
        className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface-hover"
      >
        <div className={`h-full rounded-full transition-all duration-200 ${barClass}`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}

// Status-first view of the selected task: Chinese status, one-line headline,
// progress, and the controls that make sense right now.
export default function TaskControlSection({
  taskId, taskStatus, logs = [], view: precomputed, statusText, controlTask, controlLoading = {}, pollError = null, onRefresh,
}) {
  const view = precomputed || describeTask(taskStatus, logs)
  const status = statusText || view.status
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
          <h2 id="fanya-task-headline" className="mt-2 break-words text-xl font-bold text-text">{view.headline}</h2>
          {view.detail && <p className="mt-1 break-words text-sm text-text-muted">{view.detail}</p>}
        </div>
        {updatedAt && <p className="text-xs text-text-muted">更新于 {formatTaskTime(updatedAt)}</p>}
      </div>

      {pollError && (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-warning/30 bg-warning-surface px-3 py-2 text-sm text-text">
          <WifiOff className="h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
          <p className="min-w-0 flex-1 break-words">
            {pollError.missing
              ? '找不到这个任务的记录，可能已过期被清理。下面显示的是最后一次读到的状态。'
              : `暂时读不到最新进度，正在自动重试。${pollError.message ? `（${pollError.message}）` : ''}`}
          </p>
          {!pollError.missing && onRefresh && (
            <button type="button" onClick={onRefresh} className="clay-button-secondary min-h-[44px] gap-1.5 px-3 text-sm">
              <RefreshCw className="h-4 w-4" aria-hidden="true" />立即刷新
            </button>
          )}
        </div>
      )}

      {(totalChapters > 0 || totalCourses > 0) && (
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <ProgressRow
            label="章节进度"
            value={`${doneChapters}/${totalChapters}`}
            percent={percentOf(doneChapters, totalChapters)}
            barClass="bg-primary"
          />
          <ProgressRow
            label="课程进度"
            value={`${doneCourses}/${totalCourses}${failedCourses > 0 ? `（${failedCourses} 门未完成）` : ''}`}
            percent={percentOf(doneCourses, totalCourses)}
            barClass="bg-success"
          />
        </div>
      )}

      {showVideo && (
        <div className="mt-4 rounded-xl bg-surface-hover/60 p-3">
          <ProgressRow
            label={`当前视频：${video.name}`}
            value={`${clock(video.current)} / ${clock(video.duration)}`}
            percent={percentOf(toNum(video.current), toNum(video.duration))}
            barClass="bg-primary"
          />
        </div>
      )}

      {taskId && !done && (
        <div className="mt-5 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => { void controlTask('pause') }}
            disabled={status !== 'running' || Boolean(controlLoading?.pause)}
            className="clay-button-secondary min-h-[44px] gap-1.5 px-4 text-sm"
          >
            <Pause className="h-4 w-4" aria-hidden="true" />暂停
          </button>
          <button
            type="button"
            onClick={() => { void controlTask('resume') }}
            disabled={status !== 'paused' || Boolean(controlLoading?.resume)}
            className="clay-button-secondary min-h-[44px] gap-1.5 px-4 text-sm"
          >
            <Play className="h-4 w-4" aria-hidden="true" />继续
          </button>
          <button
            type="button"
            onClick={() => {
              if (window.confirm('确定要停止当前刷课任务吗？')) void controlTask('stop')
            }}
            disabled={status === 'cancelling' || Boolean(controlLoading?.stop)}
            className="clay-button min-h-[44px] gap-1.5 border border-danger/40 px-4 text-sm text-danger hover:bg-danger-surface"
          >
            <Square className="h-4 w-4" aria-hidden="true" />停止
          </button>
        </div>
      )}

      {taskId && (
        <p className="mt-4 break-all text-xs text-text-muted">
          任务编号 <span className="font-mono">{taskId}</span>
        </p>
      )}
    </section>
  )
}
