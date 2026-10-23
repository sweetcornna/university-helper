import { useState } from 'react'
import { AlertCircle, AlertTriangle, RotateCw } from 'lucide-react'

import { ACTION_LABELS } from '../taskInsights'

const TONE = {
  danger: { box: 'border-danger/30 bg-danger-surface', text: 'text-danger', Icon: AlertCircle },
  warning: { box: 'border-warning/30 bg-warning-surface', text: 'text-warning', Icon: AlertTriangle },
}

const VISIBLE_ISSUES = 4

// "What went wrong and what to do next". Used for task failures, in-run
// retries and start errors. `role` defaults to a labelled region; pass
// role="alert" when the panel is the direct answer to a click.
export default function AttentionPanel({ id, attention, onAction, labels = {}, role, footer, className = '' }) {
  const [showAll, setShowAll] = useState(false)
  if (!attention) return null

  const tone = TONE[attention.tone] || TONE.danger
  const issues = Array.isArray(attention.issues) ? attention.issues : []
  const visible = showAll ? issues : issues.slice(0, VISIBLE_ISSUES)
  const actions = Array.isArray(attention.actions) ? attention.actions : []
  const headingId = `${id || 'attention'}-title`

  return (
    <section
      role={role}
      aria-labelledby={role ? undefined : headingId}
      className={`rounded-2xl border p-4 sm:p-5 ${tone.box} ${className}`}
    >
      <div className="flex items-start gap-3">
        <tone.Icon className={`mt-0.5 h-5 w-5 shrink-0 ${tone.text}`} aria-hidden="true" />
        <div className="min-w-0 flex-1 space-y-3">
          <div>
            <h3 id={headingId} className={`font-semibold ${tone.text}`}>{attention.title}</h3>
            {attention.summary && <p className="mt-1 text-sm leading-6 text-text">{attention.summary}</p>}
          </div>

          {visible.length > 0 && (
            <ul className="space-y-2">
              {visible.map((issue, index) => (
                <li key={`${issue.course}-${issue.chapter}-${index}`} className="rounded-xl bg-surface/80 px-3 py-2.5 text-sm">
                  {(issue.course || issue.chapter) && (
                    <p className="break-words font-semibold text-text">
                      {[issue.course, issue.chapter].filter(Boolean).join(' › ')}
                    </p>
                  )}
                  <p className="mt-0.5 break-words text-text">
                    {issue.retrying && <RotateCw className="mr-1 inline h-3.5 w-3.5 align-[-2px] text-warning" aria-hidden="true" />}
                    {issue.reason}
                  </p>
                  {issue.hint && <p className="mt-1 break-words text-text-muted">建议：{issue.hint}</p>}
                </li>
              ))}
            </ul>
          )}

          {issues.length > VISIBLE_ISSUES && (
            <button
              type="button"
              onClick={() => setShowAll((value) => !value)}
              aria-expanded={showAll}
              className="min-h-[44px] text-sm font-semibold text-primary hover:underline"
            >
              {showAll ? '收起' : `查看全部 ${issues.length} 条`}
            </button>
          )}

          {actions.length > 0 && onAction && (
            <div className="flex flex-wrap gap-2">
              {actions.map((action, index) => (
                <button
                  key={action}
                  type="button"
                  onClick={() => onAction(action)}
                  className={index === 0
                    ? 'clay-button-primary min-h-[44px] px-4 text-sm'
                    : 'clay-button-secondary min-h-[44px] px-4 text-sm'}
                >
                  {labels[action] || ACTION_LABELS[action] || action}
                </button>
              ))}
            </div>
          )}

          {footer && <p className="text-xs leading-5 text-text-muted">{footer}</p>}
        </div>
      </div>
    </section>
  )
}
