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
const USERNAME_PATTERN = /^[a-z0-9]+$/
const PASSWORD_PATTERNS = [/[A-Z]/, /[a-z]/, /\d/]

const RESEND_COOLDOWN_SECONDS = 60

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
  const [fieldErrors, setFieldErrors] = useState({})
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()
  const { markLocal } = useRuntimeProfile()
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

  const handleSendCode = async () => {
    if (sendingCode || cooldown > 0) return
    // The button stays focusable when the address is unusable: `disabled` would
    // drop it out of the tab order with nothing saying why. Validate on click
    // and name the problem instead.
    if (!EMAIL_PATTERN.test(form.email.trim())) {
      setNotice('')
      setError('')
      setFieldErrors((previous) => ({
        ...previous,
        email: '请先填写有效的邮箱地址，再获取验证码。',
      }))
      return
    }
    setError('')
    setNotice('')
    setSendingCode(true)
    try {
      await api('/auth/send-code', {
        method: 'POST',
        body: JSON.stringify({ email: form.email.trim(), scene: 'register' }),
      })
      setCooldown(RESEND_COOLDOWN_SECONDS)
      setFieldErrors((previous) => ({ ...previous, email: '' }))
      setNotice('验证码已发送，请查收邮箱，10 分钟内有效。')
    } catch (err) {
      setError(sendCodeErrorMessage(err))
    } finally {
      setSendingCode(false)
    }
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (submitting) return

    const nextErrors = {}
    const username = form.username.trim()
    const email = form.email.trim()
    if (username.length < 3 || username.length > 30) {
      nextErrors.username = '用户名需为 3–30 个字符。'
    } else if (!USERNAME_PATTERN.test(username)) {
      nextErrors.username = '用户名只能包含小写字母和数字。'
    }
    if (!email) nextErrors.email = '请输入邮箱。'
    else if (!EMAIL_PATTERN.test(email)) nextErrors.email = '请输入有效的邮箱地址。'
    if (form.password.length < 8) {
      nextErrors.password = '密码至少需要 8 个字符。'
    } else if (!PASSWORD_PATTERNS.every((pattern) => pattern.test(form.password))) {
      nextErrors.password = '密码需同时包含大写字母、小写字母和数字。'
    }
    setFieldErrors(nextErrors)
    setError('')
    if (Object.keys(nextErrors).length > 0) return

    setSubmitting(true)
    try {
      const response = await api('/auth/register', {
        method: 'POST',
        body: JSON.stringify({
          ...form,
          username,
          email,
          // Only sent when the site advertises email verification, so the
          // no-SMTP deploys keep working against the three-field schema.
          ...(codeRequired ? { code } : {}),
        }),
      })
      setToken(response.access_token || response.token, response.shuake_token)
      navigate(from, { replace: true })
    } catch (requestError) {
      if (requestError?.payload?.code === LOCAL_PROFILE_AUTH_CODE) {
        markLocal()
        navigate('/dashboard', { replace: true })
        return
      }
      const message = requestError?.message || '注册失败，请稍后重试。'
      // Verification is on but /auth/config never told us — the request failed
      // or was still in flight when the form was submitted. Reveal the code
      // field so the user can recover here instead of having to reload.
      if (requestError?.status === 400 && message.includes('请先获取邮箱验证码')) {
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
      <div className="absolute right-4 top-4 z-20">
        <ThemeToggle />
      </div>

      <section className="auth-pitch">
        <div className="auth-pitch__inner">
          <p className="auth-eyebrow auth-rise">学道</p>
          <h1 className="auth-headline auth-rise auth-delay-1">从今天起，课自己上。</h1>
          <p className="auth-lede auth-rise auth-delay-2">
            注册后绑定你的学习通账号，签到、刷课和答题交给它，你只看结果。
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
          <p className="auth-form-hint auth-rise auth-delay-2">
            {codeRequired ? '邮箱会收到一封验证码，验证后即可使用。' : '三步之内就能开始。'}
          </p>

          {/* Outside the field list on purpose: a live region nested inside one
              would be freshly inserted at the exact moment the notice appears
              and go unannounced. */}
          <div aria-live="polite">
            {notice && !error ? <p className="auth-notice mt-6">{notice}</p> : null}
          </div>

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
                onChange={(event) => {
                  setForm((previous) => ({ ...previous, username: event.target.value }))
                  setFieldErrors((previous) => ({ ...previous, username: '' }))
                }}
                required
              />
              {fieldErrors.username ? (
                <p role="alert" className="auth-error">
                  {fieldErrors.username}
                </p>
              ) : (
                <p className="text-[13px] text-auth-muted">3–30 位小写字母或数字。</p>
              )}
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

            {codeRequired && (
              <div className="auth-field auth-rise auth-delay-5">
                <label className="auth-label" htmlFor="register-code">
                  邮箱验证码
                </label>
                {/* The send button sits beside the field rather than inside it so
                    the cooldown label ("60 秒后重发") never overlaps the value. */}
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
                    onChange={(event) => setCode(event.target.value)}
                    required
                  />
                  <button
                    type="button"
                    className="auth-ghost-button"
                    onClick={handleSendCode}
                    disabled={sendingCode || cooldown > 0}
                    aria-busy={sendingCode}
                  >
                    {sendingCode && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
                    {cooldown > 0 ? `${cooldown} 秒后重发` : '发送验证码'}
                  </button>
                </div>
              </div>
            )}

            <div className="auth-field auth-rise auth-delay-6">
              <label className="auth-label" htmlFor="register-password">
                密码
              </label>
              <div className="auth-code-row">
                <input
                  id="register-password"
                  className="auth-input flex-1 min-w-0"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
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
              {fieldErrors.password ? (
                <p role="alert" className="auth-error">
                  {fieldErrors.password}
                </p>
              ) : (
                <p className="text-[13px] text-auth-muted">
                  至少 8 个字符，包含大写字母、小写字母和数字。
                </p>
              )}
            </div>

            {error && (
              <p role="alert" className="auth-error">
                {error}
              </p>
            )}

            <div className="auth-rise auth-delay-7">
              <button
                type="submit"
                className="auth-submit"
                disabled={submitting}
                aria-busy={submitting}
              >
                {submitting && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
                {submitting ? '正在创建…' : '创建学道账号'}
              </button>
            </div>
          </form>

          <div className="auth-meta auth-rise auth-delay-7">
            <span>
              已有账号？{' '}
              <Link to="/login" className="auth-link font-medium">
                返回登录
              </Link>
            </span>
          </div>
        </div>
      </section>
    </main>
  )
}
