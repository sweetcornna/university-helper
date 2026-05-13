import { useState } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { LogIn, Loader2 } from 'lucide-react'
import { api } from '../utils/api'
import { setToken } from '../utils/auth'
import { Button, Input, Card } from '../components'

export default function Login() {
  const [form, setForm] = useState({ email: '', password: '' })
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const from = location.state?.from || '/dashboard'

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
    <main className="min-h-screen flex items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <div className="flex items-center gap-3 mb-6">
          <LogIn className="w-8 h-8 text-primary" aria-hidden="true" />
          <h1 className="text-2xl font-bold">登录</h1>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <Input
            id="login-email"
            label="邮箱"
            type="email"
            autoComplete="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            required
          />
          <Input
            id="login-password"
            label="密码"
            type="password"
            autoComplete="current-password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            required
          />
          {error && (
            <p role="alert" className="text-red-600 text-sm">
              {error}
            </p>
          )}
          <Button
            type="submit"
            variant="primary"
            className="w-full inline-flex items-center justify-center gap-2"
            disabled={submitting}
            aria-busy={submitting}
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
            {submitting ? '登录中…' : '登录'}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm">
          还没有账号？{' '}
          <Link to="/register" className="text-primary hover:underline">
            注册
          </Link>
        </p>
      </Card>
    </main>
  )
}
