import { Inbox } from 'lucide-react'

export default function EmptyState({ icon: Icon = Inbox, title, hint, action, className = '' }) {
  return (
    <div
      className={`schedule-paper flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border px-6 py-10 text-center ${className}`}
    >
      <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-surface text-primary shadow-sm">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <p className="mt-1 text-sm font-semibold text-text">{title}</p>
      {hint && <p className="max-w-sm text-sm leading-6 text-text-muted">{hint}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}
