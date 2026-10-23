import { History, Loader2 } from 'lucide-react'

import { EmptyState, StatusBadge } from '../../../components'
import { translateTaskMessage } from '../../../utils/taskMessages'
import { CARD, formatTaskTime, normalizeCourseText } from '../utils'

const summaryOf = (task) => {
  const course = normalizeCourseText(task?.progress?.current_course)
  const message = translateTaskMessage(task?.message)
  return [course, message].filter(Boolean).join(' · ')
}

export default function TaskHistorySection({
  taskHistory, taskId, selectTaskFromHistory, loading = false, error = '', onRetry, onStartNew,
}) {
  return (
    <section aria-labelledby="fanya-history-title" className={CARD}>
      <div className="mb-4">
        <h2 id="fanya-history-title" className="text-xl font-semibold text-text">任务记录</h2>
        <p className="mt-1 text-sm text-text-muted">点一条记录查看它的进度和日志。</p>
      </div>

      {error && (
        <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-danger/30 bg-danger-surface px-3 py-2.5 text-sm text-danger">
          <span className="min-w-0 flex-1 break-words">任务记录没有加载出来：{translateTaskMessage(error)}</span>
          {onRetry && <button type="button" onClick={onRetry} className="clay-button-secondary min-h-[44px] px-3 text-sm">重试</button>}
        </div>
      )}

      {loading && taskHistory.length === 0 ? (
        <p role="status" className="flex items-center gap-2 py-6 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />正在读取任务记录…
        </p>
      ) : taskHistory.length === 0 ? (
        !error && (
          <EmptyState
            icon={History}
            title="还没有任务记录"
            hint="开始刷课后，每次任务都会记在这里，可以随时回来查看。"
            action={onStartNew && <button type="button" onClick={onStartNew} className="clay-button-primary min-h-[44px] px-4 text-sm">去选择课程</button>}
          />
        )
      ) : (
        <ul className="space-y-2">
          {taskHistory.map((task) => {
            const selected = task.task_id === taskId
            const summary = summaryOf(task)
            return (
              <li key={task.task_id}>
                <button
                  type="button"
                  aria-label={`查看任务 ${task.task_id}`}
                  aria-current={selected ? 'true' : undefined}
                  onClick={() => { void selectTaskFromHistory(task.task_id) }}
                  className={`min-h-[44px] w-full cursor-pointer rounded-xl border px-4 py-3 text-left transition-colors duration-200 ${
                    selected ? 'border-primary bg-primary/10' : 'border-border bg-surface hover:border-primary/40 hover:bg-surface-hover'
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <StatusBadge status={task.status} />
                    <span className="text-xs text-text-muted">{formatTaskTime(task.updated_at)}</span>
                  </div>
                  {summary && <p className="mt-2 break-words text-sm text-text">{summary}</p>}
                  <p className="mt-1 break-all font-mono text-xs text-text-muted">
                    {task.task_id}{selected ? ' · 正在查看' : ''}
                  </p>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
