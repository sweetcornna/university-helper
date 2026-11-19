import { forwardRef, useCallback, useEffect, useMemo, useRef } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'

import { LogPane, ProgressMeter, StateNotice, StatusBadge } from '../../../components'
import { GLASS_CARD_CLASS, safeStringify } from '../utils'
import {
  backgroundTaskBadge,
  backgroundTaskProgress,
  classifyBackgroundTask,
  redactForDisplay,
} from '../taskPresentation'

// Within this distance of the bottom the log keeps following new lines; a
// reader who scrolled up to an older line is left where they are.
const LOG_FOLLOW_SLACK_PX = 24

// Show log times in the reader's local clock; keep unparseable values as-is.
const formatLogTime = (value) => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

const formatLog = (log, index) => {
  const text = typeof log === 'string' ? log : log?.message || safeStringify(log)
  const timestamp = typeof log === 'object' && log?.timestamp ? String(log.timestamp) : ''
  return {
    key: `${timestamp}-${index}`,
    time: timestamp ? `[${formatLogTime(timestamp)}]` : '',
    text,
    level: String((typeof log === 'object' && log?.level) || '').toLowerCase(),
  }
}

// Detail pane for one background sign-in task: id, status, progress counts,
// terminal outcome (including "result not confirmed"), redacted raw status and
// the incremental log. The parent owns polling; this only renders.
const StatusSummary = ({ state, message }) => {
  switch (state) {
    case 'unconfirmed':
      return (
        <StateNotice kind="unknown" title="签到结果未确认" compact>
          {message ? `${message}不要重复提交。` : '请在学习通核对，不要重复提交。'}
        </StateNotice>
      )
    case 'unsaved':
      return (
        <StateNotice kind="unknown" title="最终结果未保存" compact>
          请在学习通核对签到状态，不要据此判断结果。
        </StateNotice>
      )
    case 'running':
      return <StateNotice kind="loading" compact title="执行中">{message || null}</StateNotice>
    case 'stopping':
      return <StateNotice kind="loading" compact title="取消中">{message || null}</StateNotice>
    case 'done':
      return <StateNotice kind="done" title="已完成" compact>{message || null}</StateNotice>
    case 'guided':
      return <StateNotice kind="warning" title="需在学习通完成" compact>{message || null}</StateNotice>
    case 'error':
      return <StateNotice kind="error" title="未全部完成" compact>{message || null}</StateNotice>
    case 'cancelled':
      return <StateNotice kind="disabled" title="已取消" compact>{message || null}</StateNotice>
    default:
      return (
        <StateNotice kind="unknown" title="状态未知" compact>
          {message ? `${message} ` : ''}请刷新重试，不要据此判断签到结果。
        </StateNotice>
      )
  }
}

const BackgroundTaskDetail = forwardRef(function BackgroundTaskDetail(
  { taskId, taskStatus, logs, statusLoading, onRefresh },
  logRef,
) {
  const state = classifyBackgroundTask(taskStatus)
  const badge = backgroundTaskBadge(taskStatus)
  const message = String(taskStatus?.message || taskStatus?.current_task || '')
  const progress = backgroundTaskProgress(taskStatus?.progress)
  const entries = useMemo(() => logs.map(formatLog), [logs])

  // Follow the newest log line only while the reader is at the bottom.
  const paneRef = useRef(null)
  const followRef = useRef(true)
  const setPaneRef = useCallback((node) => {
    paneRef.current = node
    if (typeof logRef === 'function') logRef(node)
    else if (logRef) logRef.current = node
  }, [logRef])
  useEffect(() => {
    followRef.current = true
  }, [taskId])
  useEffect(() => {
    const el = paneRef.current
    if (!el) return undefined
    const onScroll = () => {
      followRef.current = el.scrollHeight - el.scrollTop - el.clientHeight <= LOG_FOLLOW_SLACK_PX
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [])
  useEffect(() => {
    const el = paneRef.current
    if (el && followRef.current) el.scrollTop = el.scrollHeight
  }, [entries])
  const pretty = useMemo(() => {
    if (!taskStatus) return ''
    try {
      return JSON.stringify(redactForDisplay(taskStatus), null, 2)
    } catch (_) {
      return String(taskStatus)
    }
  }, [taskStatus])

  return (
    <section className={`${GLASS_CARD_CLASS} space-y-4`} aria-labelledby="cx-task-detail-heading">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="cx-task-detail-heading" tabIndex={-1} className="font-display text-base font-bold text-text">后台任务状态</h2>
          {taskId && (
            <p className="mt-1 break-all text-xs text-text-muted">
              任务 ID：<span className="font-code text-text">{taskId}</span>
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {taskStatus && <StatusBadge status={badge.status} label={badge.label} />}
          <button
            type="button"
            className="ui-btn-secondary ui-btn-sm"
            onClick={onRefresh}
            disabled={!taskId || statusLoading}
          >
            {statusLoading ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden="true" />
                刷新中...
              </span>
            ) : (
              <span className="inline-flex items-center gap-2">
                <RefreshCw className="h-4 w-4" aria-hidden="true" />
                刷新状态
              </span>
            )}
          </button>
        </div>
      </div>

      {!taskId ? (
        <StateNotice kind="empty" compact>未打开后台任务</StateNotice>
      ) : !taskStatus ? (
        statusLoading ? (
          <StateNotice kind="loading" role="status" compact>正在读取任务状态…</StateNotice>
        ) : (
          <StateNotice kind="unknown" compact title="暂未取得任务状态">
            请刷新重试，不要据此判断签到结果。
          </StateNotice>
        )
      ) : (
        <>
          <StatusSummary state={state} message={message} />

          {progress && (
            <ProgressMeter
              label={`已处理 ${progress.processed}/${progress.total}`}
              value={progress.total > 0 ? (progress.processed / progress.total) * 100 : 0}
              known={progress.total > 0}
              tone={progress.failed > 0 ? 'warning' : 'primary'}
              detail={[
                `成功 ${progress.succeeded} 项`,
                `失败 ${progress.failed} 项`,
                progress.currentCourse ? `当前：${progress.currentCourse}` : '',
              ].filter(Boolean).join(' · ')}
            />
          )}

          <details className="ui-panel group px-3 py-2">
            <summary className="flex min-h-[36px] items-center justify-between gap-3 text-sm text-text-muted [&::-webkit-details-marker]:hidden">
              原始状态
              <span className="font-code shrink-0 text-xs group-open:hidden">展开</span>
              <span className="font-code hidden shrink-0 text-xs group-open:inline">收起</span>
            </summary>
            <pre className="ui-well font-code mt-2 max-h-48 overflow-auto p-3 text-xs text-text">{pretty}</pre>
            <p className="ui-hint">敏感字段已隐藏。</p>
          </details>
        </>
      )}

      <div>
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <p className="text-sm font-semibold text-text">实时日志</p>
          <span className="font-code text-xs text-text-muted">{logs.length} 条</span>
        </div>
        <LogPane ref={setPaneRef} entries={entries} label="实时日志" className="max-h-64" />
      </div>
    </section>
  )
})

export default BackgroundTaskDetail
