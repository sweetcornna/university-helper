import {
  AlertTriangle,
  CheckCircle2,
  CircleSlash,
  HelpCircle,
  Inbox,
  Info,
  Loader2,
  Lock,
  WifiOff,
  XCircle,
} from 'lucide-react'
import { clsx } from 'clsx'

// One visual vocabulary for every non-content state, so loading, empty,
// permission, network, disabled, finished and unknown never look alike.
const KINDS = {
  loading: { icon: Loader2, tone: 'border-border-subtle bg-surface-hover/60 text-text-muted', iconTone: 'text-primary motion-safe:animate-spin' },
  empty: { icon: Inbox, tone: 'border-dashed border-border bg-surface text-text-muted', iconTone: 'text-primary' },
  error: { icon: XCircle, tone: 'border-danger/35 bg-danger-surface text-danger', iconTone: 'text-danger' },
  permission: { icon: Lock, tone: 'border-warning/35 bg-warning-surface text-text', iconTone: 'text-warning' },
  network: { icon: WifiOff, tone: 'border-danger/35 bg-danger-surface text-danger', iconTone: 'text-danger' },
  disabled: { icon: CircleSlash, tone: 'border-border bg-surface-hover/60 text-text-muted', iconTone: 'text-text-muted' },
  done: { icon: CheckCircle2, tone: 'border-success/35 bg-success-surface text-success', iconTone: 'text-success' },
  unknown: { icon: HelpCircle, tone: 'border-warning/35 bg-warning-surface text-text', iconTone: 'text-warning' },
  warning: { icon: AlertTriangle, tone: 'border-warning/35 bg-warning-surface text-text', iconTone: 'text-warning' },
  info: { icon: Info, tone: 'border-primary/30 bg-primary/5 text-text', iconTone: 'text-primary' },
}

export default function StateNotice({
  kind = 'info',
  title,
  children,
  action,
  role,
  compact = false,
  className,
  icon,
  ...props
}) {
  const meta = KINDS[kind] || KINDS.info
  const Icon = icon || meta.icon
  return (
    <div
      role={role}
      data-state={kind}
      className={clsx(
        'flex gap-3 rounded-lg border',
        compact ? 'items-start px-3 py-2.5' : 'flex-col items-start px-4 py-4 sm:flex-row',
        meta.tone,
        className,
      )}
      {...props}
    >
      <Icon className={clsx('mt-0.5 h-4 w-4 shrink-0', meta.iconTone)} aria-hidden="true" />
      <div className="min-w-0 flex-1 space-y-1">
        {title && <p className="text-sm font-semibold">{title}</p>}
        {children && <div className="break-words text-sm leading-6 opacity-95">{children}</div>}
      </div>
      {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
    </div>
  )
}
