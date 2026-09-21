import { useEffect, useRef, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { api } from '../utils/api'

// Seven ambient "chapter" tracks. Widths, delays and the fill loop all live in
// index.css (.auth-bar*) — this is just the scaffolding.
const CHAPTER_BARS = [0, 1, 2, 3, 4, 5, 6]

const RESEND_COOLDOWN_SECONDS = 60

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const sendCodeErrorMessage = (err) => {
  if (err?.status === 429) return err.message || '发送太频繁了，请等一分钟再试。'
  if (err?.status === 400) return err.message || '这个邮箱没有注册过，请检查后重试。'
  // 503 is the backend saying EMAIL_VERIFICATION_ENABLED is off (or SMTP is not
  // configured) — which is the default. Nothing the user does here can work, so
  // say that plainly instead of surfacing "邮箱验证未启用，请联系管理员" alone.
  if (err?.status === 503) {
    return '本站没有开启邮箱验证，暂时无法通过邮件重置密码。请联系管理员开启后再试。'
  }
  if (err?.status === 502) return '验证码邮件没能发出去，请稍后重试，或联系管理员检查邮件配置。'
  return err?.message || '验证码发送失败，请稍后重试。'
}

export default function ForgotPassword() {
  // 'email' collects the address and sends the code; 'reset' takes the code and
  // the new password.
  const [step, setStep] = useState('email')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [cooldown, setCooldown] = useState(0)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  // Separate from `submitting`: resending a code is not a password reset, and
  // sharing the flag made 重新发送 relabel the primary button to 重置中… and
  // disable it, claiming a reset was in flight when none was.
  const [sendingCode, setSendingCode] = useState(false)
  const codeInputRef = useRef(null)
  const navigate = useNavigate()

  useEffect(() => {
    if (cooldown <= 0) return undefined
    const timer = window.setTimeout(() => setCooldown((remaining) => remaining - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [cooldown])

  // Swapping the email form out for the reset form drops keyboard focus to
  // <body>. Put it on the field the user now has to fill.
  useEffect(() => {
    if (step === 'reset') codeInputRef.current?.focus()
  }, [step])

  const emailLooksValid = EMAIL_PATTERN.test(email)

  const sendCode = async () => {
    setError('')
    setNotice('')
    setSendingCode(true)
    try {
      await api('/auth/send-code', {
        method: 'POST',
        body: JSON.stringify({ email, scene: 'reset' }),
      })
      setCooldown(RESEND_COOLDOWN_SECONDS)
      setStep('reset')
      setNotice('验证码已发送，请查收邮箱，10 分钟内有效。')
    } catch (err) {
      setError(sendCodeErrorMessage(err))
    } finally {
      setSendingCode(false)
    }
  }

  const handleRequest = (e) => {
    e.preventDefault()
    if (sendingCode) return
    // Validated here rather than by disabling the button, so the control keeps
    // its place in the tab order and an unusable address gets explained.
    if (!emailLooksValid) {
      setNotice('')
      setError('请输入有效的邮箱地址。')
      return
    }
    sendCode()
  }

  const handleResend = () => {
    if (sendingCode || cooldown > 0) return
    sendCode()
  }

  const handleReset = async (e) => {
    e.preventDefault()
    if (submitting) return
    setError('')
    setSubmitting(true)
    try {
      await api('/auth/reset-password', {
        method: 'POST',
        body: JSON.stringify({ email, code, new_password: newPassword }),
      })
      navigate('/login', {
        replace: true,
        state: { notice: '密码已重置，用新密码登录吧。' },
      })
    } catch (err) {
      setError(err.message || '重置失败，请检查验证码后重试。')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-pitch">
        <div className="auth-pitch__inner">
          <p className="auth-eyebrow auth-rise">学道</p>
          <h1 className="auth-headline auth-rise auth-delay-1">忘了密码，课还得上。</h1>
          <p className="auth-lede auth-rise auth-delay-2">
            我们会把验证码发到你注册时用的邮箱。验证之后就能设置新密码，任务不受影响。
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
          <h2 className="auth-form-title auth-rise auth-delay-2">重置密码</h2>
          <p className="auth-form-hint auth-rise auth-delay-2">
            {step === 'email' ? '先确认这是你的邮箱。' : `验证码已发往 ${email}。`}
          </p>

          {/* Outside the step branch on purpose: the forms are swapped whole, so
              a live region nested inside one would be freshly inserted at the
              exact moment the notice appears and go unannounced. Empty it
              collapses to nothing. */}
          <div aria-live="polite">
            {notice && !error ? <p className="auth-notice mt-6">{notice}</p> : null}
          </div>

          {step === 'email' ? (
            <form onSubmit={handleRequest} className="auth-form" noValidate>
              <div className="auth-field auth-rise auth-delay-3">
                <label className="auth-label" htmlFor="forgot-email">
                  邮箱
                </label>
                <input
                  id="forgot-email"
                  className="auth-input"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>

              {error && (
                <p role="alert" className="auth-error">
                  {error}
                </p>
              )}

              <div className="auth-rise auth-delay-4">
                <button
                  type="submit"
                  className="auth-submit"
                  disabled={sendingCode}
                  aria-busy={sendingCode}
                >
                  {sendingCode && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
                  {sendingCode ? '发送中…' : '发送验证码'}
                </button>
              </div>
            </form>
          ) : (
            <form onSubmit={handleReset} className="auth-form" noValidate>
              <div className="auth-field auth-rise auth-delay-3">
                <label className="auth-label" htmlFor="forgot-code">
                  邮箱验证码
                </label>
                <div className="auth-code-row">
                  <input
                    id="forgot-code"
                    ref={codeInputRef}
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
                    onClick={handleResend}
                    disabled={sendingCode || cooldown > 0}
                    aria-busy={sendingCode}
                  >
                    {cooldown > 0 ? `${cooldown} 秒后重发` : '重新发送'}
                  </button>
                </div>
              </div>

              <div className="auth-field auth-rise auth-delay-4">
                <label className="auth-label" htmlFor="forgot-password">
                  新密码
                </label>
                <input
                  id="forgot-password"
                  className="auth-input"
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
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
                  {submitting ? '重置中…' : '设置新密码'}
                </button>
              </div>
            </form>
          )}

          <div className="auth-meta auth-rise auth-delay-6">
            <Link to="/login" className="auth-link">
              返回登录
            </Link>
          </div>
        </div>
      </section>
    </main>
  )
}
