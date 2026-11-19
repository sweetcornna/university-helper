import { ChevronRight, History, Loader2 } from 'lucide-react'

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
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 id="fanya-history-title" className="font-display text-base font-bold text-text">任务记录</h2>
        <span className="font-code text-xs text-text-muted">{taskHistory.length} 条</span>
      </div>

      {error && (
        <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-danger/30 bg-danger-surface px-3 py-2.5 text-sm text-danger">
          <span className="min-w-0 flex-1 break-words">任务记录没有加载出来：{translateTaskMessage(error)}</span>
          {onRetry && <button type="button" onClick={onRetry} className="ui-btn-secondary min-h-[44px] px-3 text-sm">重试</button>}
        </div>
      )}

      {loading && taskHistory.length === 0 ? (
        <p role="status" className="flex items-center gap-2 py-6 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 motion-safe:animate-spin text-primary" aria-hidden="true" />正在读取任务记录…
        </p>
      ) : taskHistory.length === 0 ? (
        !error && (
          <EmptyState
            icon={History}
            title="还没有任务记录"
            action={onStartNew && <button type="button" onClick={onStartNew} className="ui-btn-primary min-h-[44px] px-4 text-sm">去选择课程</button>}
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
                  className={`min-h-[44px] w-full cursor-pointer rounded-lg border px-3 py-2.5 text-left transition-colors duration-200 ${
                    selected ? 'border-primary/60 bg-primary/5' : 'border-border-subtle bg-surface hover:border-primary/40 hover:bg-surface-hover'
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <StatusBadge status={task.status} />
                    <span className="ml-auto text-xs text-text-muted">{formatTaskTime(task.updated_at)}</span>
                    <ChevronRight className="h-4 w-4 shrink-0 text-text-muted" aria-hidden="true" />
                  </div>
                  {summary && <p className="mt-2 break-words text-sm text-text">{summary}</p>}
                  <p className="mt-1 break-all font-code text-xs text-text-muted">
                    {task.task_id}
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
