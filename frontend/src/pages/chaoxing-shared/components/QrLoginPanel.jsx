import { useEffect, useRef } from 'react'
import { clsx } from 'clsx'
import { CheckCircle2, Loader2, QrCode, RefreshCw, XCircle } from 'lucide-react'

import useChaoxingQrLogin from '../hooks/useChaoxingQrLogin'
import { QR_STATUS, QR_STATUS_TEXT, isQrInFlight } from '../utils'

// The 学习通 App's scan-login, as an alternative to typing the password.
//
// The server hands back a finished base64 PNG, so this renders an <img> and
// polls — no QR generation library, and nothing to encode client-side. It is
// the same shape the 智慧树 page already uses.
export default function QrLoginPanel({ chaoxingRequest, onSuccess, className = '' }) {
  const { qrCode, status, message, error, start, cancel } = useChaoxingQrLogin({
    chaoxingRequest,
    onSuccess,
  })

  // Fetch a code as soon as the panel appears (the user already chose 扫码登录,
  // so making them press another button first would be noise). Guarded by a ref
  // for the same StrictMode reason as the session probe: a cancel-on-unmount
  // would throw away the only result and leave the panel empty forever.
  const startedRef = useRef(false)
  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    void start()
  }, [start])

  // Leaving the panel abandons the scan server-side rather than leaving it to
  // be swept on its TTL.
  useEffect(() => () => void cancel(), [cancel])

  const busy = status === QR_STATUS.LOADING
  const succeeded = status === QR_STATUS.SUCCESS
  const failed = status === QR_STATUS.FAILED
  const live = isQrInFlight(status)

  return (
    <div className={clsx('flex flex-col items-center gap-4', className)}>
      <div className="relative flex h-56 w-56 items-center justify-center rounded-2xl border border-border/30 bg-white p-3">
        {/* White on purpose: a QR needs a light quiet zone to stay scannable,
            so this must not follow the dark theme's surface token. */}
        {qrCode ? (
          <img
            src={`data:image/png;base64,${qrCode}`}
            alt="学习通登录二维码"
            className="h-full w-full object-contain"
          />
        ) : (
          <div className="flex flex-col items-center gap-2 text-text-muted">
            {busy ? <Loader2 className="h-6 w-6 animate-spin" /> : <QrCode className="h-8 w-8" />}
            <span className="text-xs">{busy ? '正在生成二维码…' : '暂无二维码'}</span>
          </div>
        )}
      </div>

      <p
        className={clsx(
          'flex items-center gap-2 text-sm',
          succeeded ? 'text-success' : failed ? 'text-danger' : 'text-text-muted'
        )}
        role={failed ? 'alert' : undefined}
      >
        {succeeded && <CheckCircle2 className="h-4 w-4" />}
        {failed && <XCircle className="h-4 w-4" />}
        {live && <Loader2 className="h-4 w-4 animate-spin" />}
        {error || message || QR_STATUS_TEXT[status] || ''}
      </p>

      <p className="text-center text-xs text-text-muted">
        打开学习通 App，使用右上角「扫一扫」扫描二维码并在手机上确认。
      </p>

      <button
        type="button"
        onClick={() => void start()}
        disabled={busy || succeeded}
        aria-busy={busy}
        className="min-h-[44px] cursor-pointer rounded-xl border border-border px-4 text-sm text-text/80 transition duration-200 hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-60"
      >
        <span className="flex items-center gap-2">
          <RefreshCw className={clsx('h-4 w-4', busy && 'animate-spin')} />
          {qrCode ? '刷新二维码' : '生成二维码'}
        </span>
      </button>
    </div>
  )
}
