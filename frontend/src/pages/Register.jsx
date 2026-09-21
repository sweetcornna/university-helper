import { useEffect, useState } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { api } from '../utils/api'
import { setToken } from '../utils/auth'

// Seven ambient "chapter" tracks. Widths, delays and the fill loop all live in
// index.css (.auth-bar*) — this is just the scaffolding.
const CHAPTER_BARS = [0, 1, 2, 3, 4, 5, 6]

const RESEND_COOLDOWN_SECONDS = 60

// Deliberately loose: the server is the authority on whether an address is
// deliverable. This only decides when the 发送验证码 button stops being dead.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const sendCodeErrorMessage = (err) => {
  // The backend's own messages are already user-facing Chinese, so prefer them
  // and only fill in when it stayed silent (or failed at the mail layer, where
  // the message tends to be an SMTP detail nobody can act on).
  if (err?.status === 429) return err.message || '发送太频繁了，请等一分钟再试。'
  if (err?.status === 400) return err.message || '这个邮箱不能用来注册，请换一个。'
  if (err?.status === 502) return '验证码邮件没能发出去，请稍后重试，或联系管理员检查邮件配置。'
  return err?.message || '验证码发送失败，请稍后重试。'
}

export default function Register() {
  const [form, setForm] = useState({ username: '', email: '', password: '' })
  const [code, setCode] = useState('')
  // Fails open: if /auth/config is unreachable we render the plain three-field
  // form, which is what every deploy without SMTP configured expects anyway.
  const [codeRequired, setCodeRequired] = useState(false)
  const [cooldown, setCooldown] = useState(0)
  const [sendingCode, setSendingCode] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const from = location.state?.from || '/dashboard'

  useEffect(() => {
    let active = true
    api('/auth/config')
      .then((resp) => {
        if (active) setCodeRequired(Boolean(resp?.email_verification_enabled))
      })
      .catch(() => {
        // Intentionally silent — the no-code form is the safe default.
      })
    return () => {
      active = false
    }
  }, [])

  // One-shot timer per tick rather than a long-lived interval: it self-clears
  // on unmount and can't drift past zero.
  useEffect(() => {
    if (cooldown <= 0) return undefined
    const timer = window.setTimeout(() => setCooldown((remaining) => remaining - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [cooldown])

  const emailLooksValid = EMAIL_PATTERN.test(form.email)

  const handleSendCode = async () => {
    if (sendingCode || cooldown > 0) return
    // The button stays focusable when the address is unusable: `disabled` would
    // drop it out of the tab order with nothing saying why. Validate on click
    // and name the problem instead.
    if (!emailLooksValid) {
      setNotice('')
      setError('请先填写有效的邮箱地址，再获取验证码。')
      return
    }
    setError('')
    setNotice('')
    setSendingCode(true)
    try {
      await api('/auth/send-code', {
        method: 'POST',
        body: JSON.stringify({ email: form.email, scene: 'register' }),
      })
      setCooldown(RESEND_COOLDOWN_SECONDS)
      setNotice('验证码已发送，请查收邮箱，10 分钟内有效。')
    } catch (err) {
      setError(sendCodeErrorMessage(err))
    } finally {
      setSendingCode(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (submitting) return
    setError('')
    setSubmitting(true)
    try {
      const resp = await api('/auth/register', {
        method: 'POST',
        body: JSON.stringify(codeRequired ? { ...form, code } : form),
      })
      setToken(resp.access_token || resp.token, resp.shuake_token)
      navigate(from, { replace: true })
    } catch (err) {
      const message = err?.message || '注册失败'
      // Verification is on but /auth/config never told us — the request failed
      // or was still in flight when the form was submitted. Reveal the code
      // field so the user can recover here instead of having to reload.
      if (err?.status === 400 && message.includes('请先获取邮箱验证码')) {
        setCodeRequired(true)
        setError('这个站点需要邮箱验证码，请点击「发送验证码」获取后再创建账号。')
      } else {
        setError(message)
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-pitch">
        <div className="auth-pitch__inner">
          <p className="auth-eyebrow auth-rise">学道</p>
          <h1 className="auth-headline auth-rise auth-delay-1">注册一次，之后不用再盯着。</h1>
          <p className="auth-lede auth-rise auth-delay-2">
            绑定超星学习通或智慧树的账号，课程视频自动观看、章节测验自动作答。创建账号后就能添加课程。
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
          <h2 className="auth-form-title auth-rise auth-delay-2">创建账号</h2>
          <p className="auth-form-hint auth-rise auth-delay-2">只要一个邮箱，一分钟就好。</p>

          <form onSubmit={handleSubmit} className="auth-form" noValidate>
            <div className="auth-field auth-rise auth-delay-3">
              <label className="auth-label" htmlFor="register-username">
                用户名
              </label>
              <input
                id="register-username"
                className="auth-input"
                type="text"
                autoComplete="username"
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                required
              />
            </div>

            <div className="auth-field auth-rise auth-delay-4">
              <label className="auth-label" htmlFor="register-email">
                邮箱
              </label>
              <input
                id="register-email"
                className="auth-input"
                type="email"
                autoComplete="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                required
              />
            </div>

            {codeRequired && (
              <div className="auth-field auth-rise auth-delay-5">
                <label className="auth-label" htmlFor="register-code">
                  邮箱验证码
                </label>
                <div className="auth-code-row">
                  <input
                    id="register-code"
                    className="auth-input flex-1 min-w-0"
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    placeholder="6 位数字"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    required
                  />
                  <button
                    type="button"
                    className="auth-ghost-button"
                    onClick={handleSendCode}
                    disabled={sendingCode || cooldown > 0}
                    aria-busy={sendingCode}
                  >
                    {cooldown > 0 ? `${cooldown} 秒后重发` : '发送验证码'}
                  </button>
                </div>
              </div>
            )}

            <div className="auth-field auth-rise auth-delay-5">
              <label className="auth-label" htmlFor="register-password">
                密码
              </label>
              <input
                id="register-password"
                className="auth-input"
                type="password"
                autoComplete="new-password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required
              />
            </div>

            {/* Mounted unconditionally so the region already exists when the
                notice arrives — a live region inserted at the same time as its
                content is routinely missed. Empty it collapses to nothing, so
                the form's vertical rhythm is unchanged. */}
            <div aria-live="polite">
              {notice && !error ? <p className="auth-notice">{notice}</p> : null}
            </div>

            {error && (
              <p role="alert" className="auth-error">
                {error}
              </p>
            )}

            <div className="auth-rise auth-delay-6">
              <button
                type="submit"
                className="auth-submit"
                disabled={submitting}
                aria-busy={submitting}
              >
                {submitting && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
                {submitting ? '创建中…' : '创建账号'}
              </button>
            </div>
          </form>

          <div className="auth-meta auth-rise auth-delay-7">
            <span>
              已有账号？{' '}
              <Link to="/login" className="auth-link">
                登录
              </Link>
            </span>
          </div>
        </div>
      </section>
    </main>
  )
}
