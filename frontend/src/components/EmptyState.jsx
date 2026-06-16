import { Inbox } from 'lucide-react'

/*
 * Consistent empty-list placeholder: icon + explanation + optional action,
 * replacing the bare one-line "暂无…" text scattered across the lists.
 */
export default function EmptyState({ icon: Icon = Inbox, title, hint, action, className = '' }) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border/60 px-6 py-10 text-center ${className}`}
    >
      <Icon className="h-8 w-8 text-text-muted" aria-hidden="true" />
      <p className="text-sm font-medium text-text">{title}</p>
      {hint && <p className="max-w-xs text-xs text-text-muted">{hint}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}
