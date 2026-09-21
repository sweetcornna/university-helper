import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { BookOpen, Eye, EyeOff } from 'lucide-react'
import { Button, Card, Input, ThemeToggle, useRuntimeProfile } from '../components'
import { api, LOCAL_PROFILE_AUTH_CODE } from '../utils/api'
import { setToken } from '../utils/auth'

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
      setFieldErrors((previous) => ({ ...previous, email: '请先填写有效的邮箱地址，再获取验证码。' }))
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
    <main className="relative flex min-h-screen items-center justify-center bg-background px-4 py-20 sm:px-8">
      <div className="absolute right-4 top-4 z-20"><ThemeToggle /></div>
      <section className="w-full max-w-md">
        <Card padding="spacious" tone="elevated">
          <Link to="/register" className="mb-7 flex w-fit items-center gap-3" aria-label="学道注册页">
            <span className="relative grid h-11 w-11 place-items-center overflow-hidden rounded-xl bg-secondary text-background dark:text-text">
              <BookOpen className="h-5 w-5" aria-hidden="true" />
              <span className="absolute bottom-0 right-0 h-2.5 w-2.5 bg-cta" aria-hidden="true" />
            </span>
            <span className="text-xl font-black tracking-[0.18em]">学道</span>
          </Link>

          <h1 className="text-3xl font-black tracking-tight text-text">创建账号</h1>

          <form onSubmit={handleSubmit} className="mt-7 space-y-5" noValidate>
            <Input
              id="register-username"
              label="用户名"
              type="text"
              autoComplete="username"
              value={form.username}
              onChange={(event) => {
                setForm((previous) => ({ ...previous, username: event.target.value }))
                setFieldErrors((previous) => ({ ...previous, username: '' }))
              }}
              error={fieldErrors.username}
              hint="3–30 位小写字母或数字。"
              required
            />
            <Input
              id="register-email"
              label="邮箱"
              type="email"
              autoComplete="email"
              inputMode="email"
              value={form.email}
              onChange={(event) => {
                setForm((previous) => ({ ...previous, email: event.target.value }))
                setFieldErrors((previous) => ({ ...previous, email: '' }))
              }}
              error={fieldErrors.email}
              required
            />
            {codeRequired && (
              // The send button sits beside the field rather than inside it so
              // the cooldown label ("60 秒后重发") never overlaps the value.
              <div className="flex items-start gap-3">
                <Input
                  id="register-code"
                  containerClassName="min-w-0 flex-1"
                  label="邮箱验证码"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  placeholder="6 位数字"
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  required
                />
                <Button
                  type="button"
                  variant="secondary"
                  className="mt-7 shrink-0 whitespace-nowrap"
                  loading={sendingCode}
                  loadingLabel="发送中…"
                  disabled={cooldown > 0}
                  onClick={handleSendCode}
                >
                  {cooldown > 0 ? `${cooldown} 秒后重发` : '发送验证码'}
                </Button>
              </div>
            )}
            <Input
              id="register-password"
              label="密码"
              type={showPassword ? 'text' : 'password'}
              autoComplete="new-password"
              value={form.password}
              onChange={(event) => {
                setForm((previous) => ({ ...previous, password: event.target.value }))
                setFieldErrors((previous) => ({ ...previous, password: '' }))
              }}
              error={fieldErrors.password}
              hint="至少 8 个字符，包含大写字母、小写字母和数字。"
              trailing={(
                <button
                  type="button"
                  onClick={() => setShowPassword((visible) => !visible)}
                  aria-label={showPassword ? '隐藏密码' : '显示密码'}
                  className="grid h-10 w-10 place-items-center rounded-lg text-text-muted hover:bg-surface-hover hover:text-text focus-visible:ring-offset-0"
                >
                  {showPassword ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
                </button>
              )}
              required
            />
            {notice && !error && (
              <p role="status" className="rounded-xl border border-success/30 bg-success-surface px-3 py-2.5 text-sm text-text">{notice}</p>
            )}
            {error && <p role="alert" className="rounded-xl border border-danger/30 bg-danger-surface px-3 py-2.5 text-sm text-danger">{error}</p>}
            <Button type="submit" variant="cta" size="lg" className="w-full gap-2" loading={submitting} loadingLabel="正在创建…">
              创建学道账号
            </Button>
          </form>

          <p className="mt-6 text-center text-sm text-text-muted">
            已有账号？{' '}
            <Link to="/login" className="font-bold text-primary hover:underline">返回登录</Link>
          </p>
        </Card>
      </section>
    </main>
  )
}
