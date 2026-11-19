import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Eye, EyeOff } from 'lucide-react'
import { Button, Input, StateNotice, useRuntimeProfile } from '../components'
import AuthShell from '../components/AuthShell'
import { api, LOCAL_PROFILE_AUTH_CODE } from '../utils/api'
import { setToken } from '../utils/auth'

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const USERNAME_PATTERN = /^[a-z0-9]+$/
const PASSWORD_PATTERNS = [/[A-Z]/, /[a-z]/, /\d/]

export default function Register() {
  const [form, setForm] = useState({ username: '', email: '', password: '' })
  const [error, setError] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()
  const { markLocal } = useRuntimeProfile()
  const location = useLocation()
  const from = location.state?.from || '/dashboard'

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
        body: JSON.stringify({ ...form, username, email }),
      })
      setToken(response.access_token || response.token, response.shuake_token)
      navigate(from, { replace: true })
    } catch (requestError) {
      if (requestError?.payload?.code === LOCAL_PROFILE_AUTH_CODE) {
        markLocal()
        navigate('/dashboard', { replace: true })
        return
      }
      setError(requestError.message || '注册失败，请稍后重试。')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthShell
      homeTo="/register"
      homeLabel="学道注册页"
      title="创建账号"
      footer={
        <p>
          已有账号？{' '}
          <Link
            to="/login"
            className="font-semibold text-primary underline-offset-4 hover:underline"
          >
            返回登录
          </Link>
        </p>
      }
    >
      <form onSubmit={handleSubmit} className="mt-6 space-y-4" noValidate>
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
          trailing={
            <button
              type="button"
              onClick={() => setShowPassword((visible) => !visible)}
              aria-label={showPassword ? '隐藏密码' : '显示密码'}
              className="grid h-9 w-9 place-items-center rounded-md text-text-muted hover:bg-surface-hover hover:text-text focus-visible:ring-offset-0"
            >
              {showPassword ? (
                <EyeOff className="h-4 w-4" aria-hidden="true" />
              ) : (
                <Eye className="h-4 w-4" aria-hidden="true" />
              )}
            </button>
          }
          required
        />
        {error && (
          <StateNotice kind="error" role="alert" compact>
            {error}
          </StateNotice>
        )}
        <Button
          type="submit"
          variant="primary"
          size="lg"
          className="w-full gap-2"
          loading={submitting}
          loadingLabel="正在创建…"
        >
          创建学道账号
        </Button>
      </form>
    </AuthShell>
  )
}
