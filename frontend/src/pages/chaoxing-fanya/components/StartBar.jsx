import { Loader2, Play } from 'lucide-react'

import AttentionPanel from './AttentionPanel'
import { CARD } from '../utils'

// The one place a task is started. Shown under the course list (sticky on
// small screens), on 学习配置 and on 执行与日志, so 学习配置 is optional.
export default function StartBar({
  selectedCount,
  limitCount = 0,
  summary,
  loading,
  isRunning,
  canStart = true,
  blockedReason = '',
  startError,
  onStart,
  onAction,
  onEditSettings,
  sticky = false,
}) {
  const disabled = loading || isRunning || !canStart || selectedCount === 0
  const reason = isRunning
    ? '已有任务在运行，结束或停止后才能开始新的。'
    : selectedCount === 0
      ? '先勾选至少一门课程。'
      : blockedReason

  return (
    <div className={`space-y-3 ${sticky ? 'sticky bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-20 lg:bottom-4' : ''}`}>
      {startError && (
        <AttentionPanel id="fanya-start-error" role="alert" attention={{ tone: 'danger', ...startError, summary: startError.detail }} onAction={onAction} />
      )}
      {/* Sticky on phones: one row (count + button) so the course list stays visible. */}
      <div className={`${CARD} flex gap-3 sm:flex-row sm:items-center sm:justify-between ${sticky ? 'flex-row items-center shadow-lg' : 'flex-col'}`}>
        <div className="min-w-0 text-sm">
          <p className="font-semibold text-text">
            已选 {selectedCount} 门课程{limitCount > 0 ? `（${limitCount} 门设了终点）` : ''}
          </p>
          <p className={`mt-0.5 break-words text-text-muted ${sticky ? 'hidden sm:block' : ''}`}>
            {summary}
            {onEditSettings && (
              <>
                {' · '}
                <button type="button" onClick={onEditSettings} className="inline-flex min-h-[44px] items-center font-semibold text-primary hover:underline sm:min-h-0">
                  修改配置
                </button>
              </>
            )}
          </p>
          {reason && <p id="fanya-start-reason" className="mt-1 text-text-muted">{reason}</p>}
        </div>
        <button
          type="button"
          onClick={() => { void onStart() }}
          disabled={disabled}
          aria-busy={loading || undefined}
          aria-describedby={reason ? 'fanya-start-reason' : undefined}
          className={`clay-button-primary min-h-[48px] shrink-0 gap-2 ${sticky ? 'px-4 sm:px-6' : 'px-6'}`}
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Play className="h-4 w-4" aria-hidden="true" />}
          {loading ? '启动中...' : '开始刷课'}
        </button>
      </div>
    </div>
  )
}
