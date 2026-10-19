import { UserRound } from 'lucide-react'

const maskAccount = (value) => {
  const text = String(value || '').trim()
  return /^\d{11}$/.test(text) ? `${text.slice(0, 3)}****${text.slice(-4)}` : text
}

// Header shortcut to the page's 账号 tab; shows who is signed in to the platform.
export default function AccountChip({ ready, account, onClick }) {
  const label = ready ? maskAccount(account) || '已登录' : '未登录'
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ready ? `平台账号：${label}` : '平台账号：未登录'}
      className={`inline-flex min-h-[40px] items-center gap-2 rounded-full border px-3 text-sm font-semibold ${
        ready
          ? 'border-success/30 bg-success-surface text-success'
          : 'border-border bg-surface text-text-muted hover:text-text'
      }`}
    >
      <UserRound className="h-4 w-4" aria-hidden="true" />
      {label}
    </button>
  )
}
