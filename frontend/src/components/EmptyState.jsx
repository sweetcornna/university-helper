import { Inbox } from 'lucide-react'

export default function EmptyState({ icon: Icon = Inbox, title, hint, action, className = '' }) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-surface px-6 py-9 text-center ${className}`}
    >
      <span className="grid h-10 w-10 place-items-center rounded-md border border-border bg-surface text-primary">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <p className="mt-1 text-sm font-semibold text-text">{title}</p>
      {hint && <p className="max-w-sm text-sm leading-6 text-text-muted">{hint}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}
