import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Eye, EyeOff } from 'lucide-react'
import { Button, Input, StateNotice, useRuntimeProfile } from '../components'
import AuthShell from '../components/AuthShell'
import { api, LOCAL_PROFILE_AUTH_CODE } from '../utils/api'
import { setToken } from '../utils/auth'

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function Login() {
  const [form, setForm] = useState({ email: '', password: '' })
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
    <AuthShell
      homeTo="/login"
      homeLabel="学道登录页"
      title="登录"
      footer={
        <p>
          还没有账号？{' '}
          <Link
            to="/register"
            className="font-semibold text-primary underline-offset-4 hover:underline"
          >
            创建账号
          </Link>
        </p>
      }
    >
      <form onSubmit={handleSubmit} className="mt-6 space-y-4" noValidate>
        <Input
          id="login-email"
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
          id="login-password"
          label="密码"
          type={showPassword ? 'text' : 'password'}
          autoComplete="current-password"
          value={form.password}
          onChange={(event) => {
            setForm((previous) => ({ ...previous, password: event.target.value }))
            setFieldErrors((previous) => ({ ...previous, password: '' }))
          }}
          error={fieldErrors.password}
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
          loadingLabel="正在登录…"
        >
          登录学道
        </Button>
      </form>
    </AuthShell>
  )
}
