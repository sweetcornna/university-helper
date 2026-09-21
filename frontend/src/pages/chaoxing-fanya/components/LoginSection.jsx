import { useState } from 'react'

import { Input } from '../../../components'
import QrLoginPanel from '../../chaoxing-shared/components/QrLoginPanel'
import { CARD, formatTaskTime } from '../utils'

// Three states, driven by useAuthentication's session probe:
//   probing  → a short placeholder, so the form never flashes before hiding;
//   active   → a compact status line + 切换账号, no password asked for;
//   inactive → exactly the credential form this page has always shown.
export default function LoginSection({
  username,
  setUsername,
  password,
  setPassword,
  loginLoading,
  handleLogin,
  sessionStatus = 'inactive',
  sessionUsername = '',
  sessionExpiresAt = '',
  switchAccount,
  switchLoading = false,
  credentialsRequired = false,
  qrRequest,
  onQrSuccess,
}) {
  // Two ways to create the same server-held session: type the password, or scan
  // with the 学习通 App. Both end up persisted server-side, so a login here (by
  // either method) is inherited by the 签到 page.
  const [mode, setMode] = useState('password')

  if (sessionStatus === 'probing') {
    return (
      <section className={CARD} aria-busy="true">
        <h2 className="mb-2 text-xl font-semibold text-text">登录账号</h2>
        <p className="text-sm text-text-muted">正在检查学习通登录状态，请稍候…</p>
      </section>
    )
  }

  const sessionActive = sessionStatus === 'active'
  const showForm = !sessionActive || credentialsRequired

  return (
    <section className={CARD}>
      <h2 className="mb-4 text-xl font-semibold text-text">
        {sessionActive ? '学习通登录状态' : '登录账号'}
      </h2>

      {sessionActive && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/30 bg-surface/60 px-4 py-3">
          <p className="text-sm text-text">
            已登录学习通账号
            <span className="mx-1 font-semibold">{sessionUsername || '（已保存的账号）'}</span>
            <span className="block text-xs text-text-muted sm:mt-1">
              {sessionExpiresAt
                ? `登录态有效期至 ${formatTaskTime(sessionExpiresAt)}，期间无需再次输入密码。`
                : '登录态由服务器保存，无需再次输入密码。'}
            </span>
          </p>

          <button
            type="button"
            onClick={switchAccount}
            disabled={switchLoading}
            aria-busy={switchLoading}
            className="min-h-[44px] cursor-pointer rounded-lg border border-border px-4 text-sm text-text/80 transition duration-200 hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {switchLoading ? '切换中...' : '切换账号'}
          </button>
        </div>
      )}

      {sessionActive && credentialsRequired && (
        <p
          role="alert"
          className="mb-4 rounded-xl bg-warning-surface px-4 py-3 text-sm text-warning"
        >
          启动任务需要把账号密码交给后台执行，请在下方填写后重新点击「开始任务」。
        </p>
      )}

      {showForm && qrRequest && (
        <div
          className="mb-4 inline-flex rounded-xl border border-border p-1"
          role="tablist"
          aria-label="登录方式"
        >
          {[
            { key: 'password', label: '账号密码' },
            { key: 'qr', label: '扫码登录' },
          ].map((tab) => (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={mode === tab.key}
              onClick={() => setMode(tab.key)}
              className={`min-h-[40px] cursor-pointer rounded-lg px-4 text-sm font-medium transition-colors ${
                mode === tab.key
                  ? 'bg-primary text-white'
                  : 'text-text-muted hover:bg-surface-hover'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}

      {showForm && mode === 'qr' && qrRequest && (
        <QrLoginPanel chaoxingRequest={qrRequest} onSuccess={onQrSuccess} />
      )}

      {showForm && mode === 'password' && (
        <form className="grid gap-4 md:grid-cols-2" onSubmit={handleLogin} noValidate>
          <Input
            id="fanya-username"
            label="超星账号"
            name="cx-username"
            autoComplete="username"
            placeholder="请输入超星账号"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />

          <Input
            id="fanya-password"
            label="密码"
            type="password"
            name="cx-password"
            autoComplete="current-password"
            placeholder="请输入密码"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />

          <button
            type="submit"
            disabled={loginLoading}
            aria-busy={loginLoading}
            className="min-h-[44px] cursor-pointer rounded-xl bg-primary px-6 py-3 font-medium text-white transition duration-200 hover:bg-primary/90 disabled:cursor-not-allowed disabled:bg-text-muted md:col-span-2"
          >
            {loginLoading ? '登录中...' : '登录并获取课程'}
          </button>
        </form>
      )}
    </section>
  )
}
