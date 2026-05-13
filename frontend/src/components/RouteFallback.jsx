import { Loader2 } from 'lucide-react'

export default function RouteFallback() {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="加载中"
      className="min-h-screen flex items-center justify-center bg-background"
    >
      <div className="flex items-center gap-3 text-text-muted">
        <Loader2 className="w-5 h-5 animate-spin text-primary" aria-hidden="true" />
        <span className="text-sm">加载中…</span>
      </div>
    </div>
  )
}
