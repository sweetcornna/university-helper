import { useEffect, useId, useState } from 'react'
import { Copy, Download, X } from 'lucide-react'
import Button from './Button'
import { useToast } from './toastContext'
import { api } from '../utils/api'
import { isAuthenticated } from '../utils/auth'
import { shouldShowUpdateNotice, skipUpdateVersion, snoozeUpdateNotice } from '../utils/updateNotice'

function CommandBlock({ label, command, onCopy }) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-semibold text-text-muted">{label}</p>
      <div className="flex items-stretch gap-2">
        <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs text-text">
          {command}
        </code>
        <Button variant="ghost" size="icon" onClick={() => onCopy(command)} aria-label={`复制${label}命令`}>
          <Copy className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>
    </div>
  )
}

// Server edition only: tells an administrator that a newer release exists and
// how to install it. Non-admins get 403 from the endpoint and never see it.
export default function UpdateNotice() {
  const [status, setStatus] = useState(null)
  const [open, setOpen] = useState(false)
  const toast = useToast()
  const titleId = useId()

  useEffect(() => {
    if (!isAuthenticated()) return undefined
    let active = true
    api('/system/update')
      .then((result) => {
        if (!active || !shouldShowUpdateNotice(result)) return
        setStatus(result)
        setOpen(true)
      })
      .catch(() => {
        // 403 for non-admins, 404 on older servers, offline: nothing to show.
      })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!open) return undefined
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        snoozeUpdateNotice()
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  if (!open || !status) return null

  const later = () => {
    snoozeUpdateNotice()
    setOpen(false)
  }
  const skip = () => {
    skipUpdateVersion(status.latest)
    setOpen(false)
  }
  const copy = async (command) => {
    try {
      await navigator.clipboard.writeText(command)
      toast.success('命令已复制')
    } catch {
      toast.error('复制失败，请手动选中命令')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <Download className="h-5 w-5 text-primary" aria-hidden="true" />
            <h2 id={titleId} className="text-lg font-bold text-text">
              学道有新版本
            </h2>
          </div>
          <Button variant="ghost" size="icon" onClick={later} aria-label="关闭，稍后提醒">
            <X className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>

        <div className="space-y-4 overflow-y-auto px-5 py-4 text-sm text-text">
          <p>
            当前版本 <strong>{status.current}</strong>，最新版本 <strong>{status.latest}</strong>。
            这条提示只有管理员能看到。
          </p>

          {status.notes && (
            <div className="max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-background px-3 py-2 text-xs leading-5 text-text-muted">
              {status.notes}
            </div>
          )}

          {status.html_url && (
            <a
              href={status.html_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block text-sm font-semibold text-primary underline-offset-4 hover:underline"
            >
              在 GitHub 查看完整更新说明
            </a>
          )}

          {status.commands && (
            <div className="space-y-3">
              <p>在服务器上进入安装目录，运行下面任意一条命令即可更新，数据和 .env 会保留：</p>
              <CommandBlock label="Linux / macOS" command={status.commands.bash} onCopy={copy} />
              <CommandBlock label="Windows PowerShell" command={status.commands.powershell} onCopy={copy} />
            </div>
          )}
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-border px-5 py-3">
          <Button variant="ghost" size="sm" onClick={skip}>
            跳过这个版本
          </Button>
          <Button variant="primary" size="sm" onClick={later}>
            稍后提醒
          </Button>
        </div>
      </div>
    </div>
  )
}
