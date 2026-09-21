import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react'
import { ToastContext } from './toastContext'

const DURATIONS = { success: 4500, info: 4000, error: 7000 }

const STYLES = {
  success: 'border-success/30 bg-success-surface text-success',
  error: 'border-danger/30 bg-danger-surface text-danger',
  info: 'border-primary/30 bg-surface text-text',
}

const ICONS = { success: CheckCircle2, error: AlertCircle, info: Info }
const MAX_VISIBLE = 4
let counter = 0

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const timers = useRef(new Map())

  const dismiss = useCallback((id) => {
    setToasts((previous) => previous.filter((toast) => toast.id !== id))
    const timer = timers.current.get(id)
    if (timer) clearTimeout(timer)
    timers.current.delete(id)
  }, [])

  useEffect(() => {
    const visibleIds = new Set(toasts.map((toast) => toast.id))
    timers.current.forEach((timer, id) => {
      if (!visibleIds.has(id)) {
        clearTimeout(timer)
        timers.current.delete(id)
      }
    })
  }, [toasts])

  useEffect(() => () => {
    timers.current.forEach((timer) => clearTimeout(timer))
    timers.current.clear()
  }, [])

  const push = useCallback((type, message, options = {}) => {
    if (!message) return undefined
    const normalizedType = ICONS[type] ? type : 'info'
    const id = ++counter
    setToasts((previous) => [
      ...previous.slice(-(MAX_VISIBLE - 1)),
      { id, type: normalizedType, message: String(message) },
    ])

    const duration = options.duration ?? DURATIONS[normalizedType] ?? 4000
    if (duration > 0) {
      timers.current.set(id, setTimeout(() => dismiss(id), duration))
    }
    return id
  }, [dismiss])

  const api = useMemo(() => ({
    notify: push,
    success: (message, options) => push('success', message, options),
    error: (message, options) => push('error', message, options),
    info: (message, options) => push('info', message, options),
    dismiss,
  }), [dismiss, push])

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        className="pointer-events-none fixed inset-x-0 top-[max(1rem,env(safe-area-inset-top))] z-[200] flex flex-col items-center gap-2 px-4 sm:inset-x-auto sm:right-4 sm:items-end"
        aria-live="polite"
      >
        {toasts.map((toast) => {
          const Icon = ICONS[toast.type] || Info
          return (
            <div
              key={toast.id}
              role={toast.type === 'error' ? 'alert' : 'status'}
              className={`pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-xl border px-4 py-3 text-sm shadow-xl animate-fade-in ${STYLES[toast.type] || STYLES.info}`}
            >
              <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="flex-1 whitespace-pre-line break-words leading-5">{toast.message}</span>
              <button
                type="button"
                onClick={() => dismiss(toast.id)}
                aria-label="关闭通知"
                className="shrink-0 rounded-md p-1 opacity-70 hover:bg-black/5 hover:opacity-100 focus-visible:ring-offset-0 dark:hover:bg-white/10"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}
