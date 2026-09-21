import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Loader2 } from 'lucide-react'

import { ThemeToggle, useRuntimeProfile } from '../components'
import { api, LOCAL_PROFILE_AUTH_CODE } from '../utils/api'
import { setToken } from '../utils/auth'

// Seven ambient "chapter" tracks, same scaffolding ForgotPassword uses; widths,
// delays and the fill loop live in index.css (.auth-bar*).
const CHAPTER_BARS = [0, 1, 2, 3, 4, 5, 6]

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function Login() {
  const [form, setForm] = useState({ email: '', password: '' })
  const [error, setError] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  // The whole reset flow runs on /auth/send-code, which hard-fails 503 unless
  // EMAIL_VERIFICATION_ENABLED is on — and off is the default. So the link is
  // opt-in: only a config response that says "enabled" renders it. A failed or
  // in-flight request leaves it hidden, because the flow behind it provably
  // cannot succeed in that state.
  const [resetEnabled, setResetEnabled] = useState(false)
  const navigate = useNavigate()
  const { markLocal } = useRuntimeProfile()
  const location = useLocation()
  const from = location.state?.from || '/dashboard'
  // Set by ForgotPassword after a successful reset.
  const notice = location.state?.notice || ''

  useEffect(() => {
    let active = true
    api('/auth/config')
      .then((resp) => {
        if (active) setResetEnabled(Boolean(resp?.email_verification_enabled))
      })
      .catch(() => {
        // Intentionally silent — hiding the link is the safe default.
      })
    return () => {
      active = false
    }
  }, [])

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (submitting) return

    const nextErrors = {}
    const email = form.email.trim()
    if (!email) nextErrors.email = '请输入邮箱。'
    else if (!EMAIL_PATTERN.test(email)) nextErrors.email = '请输入有效的邮箱地址。'
    if (!form.password) nextErrors.password = '请输入密码。'
    setFieldErrors(nextErrors)
    setError('')
    if (Object.keys(nextErrors).length > 0) return

    setSubmitting(true)
    try {
      const response = await api('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ ...form, email }),
      })
      setToken(response.access_token || response.token, response.shuake_token)
      navigate(from, { replace: true })
    } catch (requestError) {
      if (requestError?.payload?.code === LOCAL_PROFILE_AUTH_CODE) {
        markLocal()
        navigate('/dashboard', { replace: true })
        return
      }
      setError(requestError.message || '登录失败，请检查邮箱和密码。')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <div className="absolute right-4 top-4 z-20">
        <ThemeToggle />
      </div>

      <section className="auth-pitch">
        <div className="auth-pitch__inner">
          <p className="auth-eyebrow auth-rise">学道</p>
          <h1 className="auth-headline auth-rise auth-delay-1">回来接着上课。</h1>
          <p className="auth-lede auth-rise auth-delay-2">
            登录后，课程进度、任务日志和答题设置都在原处等你，接着上次的地方继续。
          </p>
          <div className="auth-bars auth-rise auth-delay-3" aria-hidden="true">
            {CHAPTER_BARS.map((index) => (
              <div key={index} className="auth-bar">
                <div className="auth-bar__fill" />
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="auth-panel">
        <div className="auth-panel__inner">
          <h2 className="auth-form-title auth-rise auth-delay-2">登录</h2>
          <p className="auth-form-hint auth-rise auth-delay-2">用注册时的邮箱和密码。</p>

          {/* Outside the form swap on purpose, same as ForgotPassword: a live
              region nested inside would be freshly inserted at the exact moment
              the notice appears and go unannounced. */}
          <div aria-live="polite">
            {notice && !error ? <p className="auth-notice mt-6">{notice}</p> : null}
          </div>

          <form onSubmit={handleSubmit} className="auth-form" noValidate>
            <div className="auth-field auth-rise auth-delay-3">
              <label className="auth-label" htmlFor="login-email">
                邮箱
              </label>
              <input
                id="login-email"
                className="auth-input"
                type="email"
                autoComplete="email"
                inputMode="email"
                value={form.email}
                onChange={(event) => {
                  setForm((previous) => ({ ...previous, email: event.target.value }))
                  setFieldErrors((previous) => ({ ...previous, email: '' }))
                }}
                required
              />
              {fieldErrors.email && (
                <p role="alert" className="auth-error">
                  {fieldErrors.email}
                </p>
              )}
            </div>

            <div className="auth-field auth-rise auth-delay-4">
              <label className="auth-label" htmlFor="login-password">
                密码
              </label>
              <div className="auth-code-row">
                <input
                  id="login-password"
                  className="auth-input flex-1 min-w-0"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  value={form.password}
                  onChange={(event) => {
                    setForm((previous) => ({ ...previous, password: event.target.value }))
                    setFieldErrors((previous) => ({ ...previous, password: '' }))
                  }}
                  required
                />
                <button
                  type="button"
                  className="auth-ghost-button px-3"
                  onClick={() => setShowPassword((visible) => !visible)}
                  aria-label={showPassword ? '隐藏密码' : '显示密码'}
                  aria-pressed={showPassword}
                >
                  {showPassword ? (
                    <EyeOff className="h-4 w-4" aria-hidden="true" />
                  ) : (
                    <Eye className="h-4 w-4" aria-hidden="true" />
                  )}
                </button>
              </div>
              {fieldErrors.password && (
                <p role="alert" className="auth-error">
                  {fieldErrors.password}
                </p>
              )}
            </div>

            {error && (
              <p role="alert" className="auth-error">
                {error}
              </p>
            )}

            <div className="auth-rise auth-delay-5">
              <button
                type="submit"
                className="auth-submit"
                disabled={submitting}
                aria-busy={submitting}
              >
                {submitting && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
                {submitting ? '正在登录…' : '登录学道'}
              </button>
            </div>
          </form>

          <div className="auth-meta auth-rise auth-delay-6">
            <span>
              还没有账号？{' '}
              <Link to="/register" className="auth-link font-medium">
                创建账号
              </Link>
            </span>
            {resetEnabled && (
              <Link to="/forgot-password" className="auth-link">
                忘记密码
              </Link>
            )}
          </div>
        </div>
      </section>
    </main>
  )
}
