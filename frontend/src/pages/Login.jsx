import { useEffect, useState } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { api } from '../utils/api'
import { setToken } from '../utils/auth'

// Seven ambient "chapter" tracks. Widths, delays and the fill loop all live in
// index.css (.auth-bar*) — this is just the scaffolding.
const CHAPTER_BARS = [0, 1, 2, 3, 4, 5, 6]

export default function Login() {
  const [form, setForm] = useState({ email: '', password: '' })
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  // The whole reset flow runs on /auth/send-code, which hard-fails 503 unless
  // EMAIL_VERIFICATION_ENABLED is on — and off is the default. So the link is
  // opt-in: only a config response that says "enabled" renders it. A failed or
  // in-flight request leaves it hidden, because the flow behind it provably
  // cannot succeed in that state.
  const [resetEnabled, setResetEnabled] = useState(false)
  const navigate = useNavigate()
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

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (submitting) return
    setError('')
    setSubmitting(true)
    try {
      const resp = await api('/auth/login', {
        method: 'POST',
        body: JSON.stringify(form),
      })
      setToken(resp.access_token || resp.token, resp.shuake_token)
      navigate(from, { replace: true })
    } catch (err) {
      setError(err.message || '登录失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-pitch">
        <div className="auth-pitch__inner">
          <p className="auth-eyebrow auth-rise">学道</p>
          <h1 className="auth-headline auth-rise auth-delay-1">让课程自己上完。</h1>
          <p className="auth-lede auth-rise auth-delay-2">
            连接超星学习通和智慧树，自动观看课程视频、自动作答章节测验。你去忙别的，进度自己往前走。
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
          <p className="auth-form-hint auth-rise auth-delay-2">用你的邮箱和密码继续。</p>

          <form onSubmit={handleSubmit} className="auth-form" noValidate>
            {notice && (
              <p className="auth-notice auth-rise auth-delay-3">{notice}</p>
            )}

            <div className="auth-field auth-rise auth-delay-3">
              <label className="auth-label" htmlFor="login-email">
                邮箱
              </label>
              <input
                id="login-email"
                className="auth-input"
                type="email"
                autoComplete="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                required
              />
            </div>

            <div className="auth-field auth-rise auth-delay-4">
              <label className="auth-label" htmlFor="login-password">
                密码
              </label>
              <input
                id="login-password"
                className="auth-input"
                type="password"
                autoComplete="current-password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required
              />
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
                {submitting ? '登录中…' : '登录'}
              </button>
            </div>
          </form>

          <div className="auth-meta auth-rise auth-delay-6">
            {resetEnabled && (
              <Link to="/forgot-password" className="auth-link">
                忘记密码
              </Link>
            )}
            <span>
              还没有账号？{' '}
              <Link to="/register" className="auth-link">
                创建账号
              </Link>
            </span>
          </div>
        </div>
      </section>
    </main>
  )
}
