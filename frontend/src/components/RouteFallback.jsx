import { Loader2 } from 'lucide-react'

export default function RouteFallback() {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="加载中"
      className="flex min-h-screen items-center justify-center bg-background px-6"
    >
      <div className="ui-index-card flex items-center gap-3 px-5 py-4 text-text-muted">
        <Loader2 className="h-4 w-4 text-primary motion-safe:animate-spin" aria-hidden="true" />
        <span className="text-sm">加载中…</span>
      </div>
    </div>
  )
}
