import { useCallback, useMemo, useRef, useState } from 'react'
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react'
import { ToastContext } from './toastContext'

/*
 * Single app-wide notification surface. Replaces the three ad-hoc mechanisms
 * the pages used to roll themselves (ChaoxingSignin's bottom-of-form banner,
 * ChaoxingFanya's twin top divs, Zhihuishu's single notice slot) — none of
 * which were reliably visible, none announced to screen readers, and each
 * styled differently.
 *
 * Toasts render in a fixed live region so the result is seen no matter which
 * tab/section the user is on, are announced (role=status / role=alert), and
 * auto-dismiss without covering content permanently.
 */

const DURATIONS = { success: 4500, info: 4000, error: 7000 }

const STYLES = {
  success: 'border-green-500/30 bg-green-50 text-green-800',
  error: 'border-red-500/30 bg-red-50 text-red-800',
  info: 'border-primary/30 bg-surface text-text',
}

const ICONS = { success: CheckCircle2, error: AlertCircle, info: Info }

// Monotonic id source — module scope so ids never collide across providers.
let counter = 0

const MAX_VISIBLE = 4

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const timers = useRef(new Map())

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
  }, [])

  const push = useCallback(
    (type, message, opts = {}) => {
      if (!message) return undefined
      const normalizedType = ICONS[type] ? type : 'info'
      const id = ++counter
      setToasts((prev) => [
        ...prev.slice(-(MAX_VISIBLE - 1)),
        { id, type: normalizedType, message: String(message) },
      ])
      const duration = opts.duration ?? DURATIONS[normalizedType] ?? 4000
      if (duration > 0) {
        timers.current.set(
          id,
          setTimeout(() => dismiss(id), duration)
        )
      }
      return id
    },
    [dismiss]
  )

  const api = useMemo(
    () => ({
      notify: push,
      success: (message, opts) => push('success', message, opts),
      error: (message, opts) => push('error', message, opts),
      info: (message, opts) => push('info', message, opts),
      dismiss,
    }),
    [push, dismiss]
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        className="pointer-events-none fixed inset-x-0 top-4 z-[200] flex flex-col items-center gap-2 px-4 sm:inset-x-auto sm:right-4 sm:items-end"
        aria-live="polite"
      >
        {toasts.map((t) => {
          const Icon = ICONS[t.type] || Info
          return (
            <div
              key={t.id}
              role={t.type === 'error' ? 'alert' : 'status'}
              className={`pointer-events-auto flex w-full max-w-sm items-start gap-2 rounded-xl border px-4 py-3 text-sm shadow-lg backdrop-blur-sm animate-fade-in ${
                STYLES[t.type] || STYLES.info
              }`}
            >
              <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="flex-1 whitespace-pre-line break-words">{t.message}</span>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                aria-label="关闭通知"
                className="shrink-0 rounded p-0.5 opacity-60 transition-opacity hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
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
