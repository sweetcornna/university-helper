import { useEffect, useMemo, useRef, useState } from 'react'

import { translateTaskMessage } from '../../../utils/taskMessages'
import { CARD } from '../utils'

const LEVELS = {
  success: { label: '成功', className: 'border-success/30 bg-success-surface text-success' },
  warning: { label: '警告', className: 'border-warning/30 bg-warning-surface text-warning' },
  error: { label: '错误', className: 'border-danger/30 bg-danger-surface text-danger' },
  info: { label: '信息', className: 'border-border bg-surface-hover text-text-muted' },
}

const timeOf = (value) => {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('zh-CN', { hour12: false })
}

export default function LogSection({ logs = [] }) {
  const [problemsOnly, setProblemsOnly] = useState(false)
  const boxRef = useRef(null)
  const stickRef = useRef(true)

  const problemCount = useMemo(() => logs.filter((item) => item.level === 'warning' || item.level === 'error').length, [logs])
  const visible = problemsOnly ? logs.filter((item) => item.level === 'warning' || item.level === 'error') : logs

  // Follow new lines only while the reader is already at the bottom.
  useEffect(() => {
    const box = boxRef.current
    if (box && stickRef.current) box.scrollTop = box.scrollHeight
  }, [visible.length])

  return (
    <section aria-labelledby="fanya-log-title" className={CARD}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id="fanya-log-title" className="text-lg font-semibold text-text">任务日志</h2>
        {problemCount > 0 && (
          <button
            type="button"
            aria-pressed={problemsOnly}
            onClick={() => setProblemsOnly((value) => !value)}
            className={`min-h-[44px] rounded-xl border px-3 text-sm font-semibold ${
              problemsOnly ? 'border-primary bg-primary/10 text-primary' : 'border-border text-text-muted hover:text-text'
            }`}
          >
            只看警告和错误（{problemCount}）
          </button>
        )}
      </div>

      {/* Not aria-live: the task headline above announces status changes; a
          live log would read every line aloud. It scrolls, so it must be
          keyboard-focusable (WCAG 2.1.1). */}
      <div
        ref={boxRef}
        role="log"
        aria-label="任务日志"
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex="0"
        onScroll={(event) => {
          const box = event.currentTarget
          stickRef.current = box.scrollHeight - box.scrollTop - box.clientHeight < 24
        }}
        className="max-h-80 overflow-y-auto rounded-xl border border-border bg-background/60 p-2 sm:p-3"
      >
        {visible.length === 0 ? (
          <p className="px-2 py-4 text-sm text-text-muted">{logs.length === 0 ? '还没有日志。任务开始后，每一步都会记在这里。' : '没有警告或错误。'}</p>
        ) : (
          <ol className="space-y-1">
            {visible.map((item, index) => {
              const level = LEVELS[item.level] || LEVELS.info
              return (
                <li key={`${item.timestamp}-${index}`} className="flex items-start gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-surface">
                  <time dateTime={item.timestamp} className="w-[4.5rem] shrink-0 pt-0.5 font-mono text-xs tabular-nums text-text-muted">{timeOf(item.timestamp)}</time>
                  <span className={`shrink-0 rounded-md border px-1.5 text-xs font-semibold leading-5 ${level.className}`}>{level.label}</span>
                  <span className="min-w-0 flex-1 break-words leading-6 text-text">{translateTaskMessage(item.message)}</span>
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </section>
  )
}
