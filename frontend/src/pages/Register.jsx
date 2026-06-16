import { useState } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { UserPlus, Loader2 } from 'lucide-react'
import { api } from '../utils/api'
import { setToken } from '../utils/auth'
import { Button, Input, Card } from '../components'

export default function Register() {
  const [form, setForm] = useState({ username: '', email: '', password: '' })
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
      const resp = await api('/auth/register', {
        method: 'POST',
        body: JSON.stringify(form),
      })
      setToken(resp.access_token || resp.token, resp.shuake_token)
      navigate(from, { replace: true })
    } catch (err) {
      setError(err.message || '注册失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <div className="flex items-center gap-3 mb-6">
          <UserPlus className="w-8 h-8 text-primary" aria-hidden="true" />
          <h1 className="text-2xl font-bold">注册</h1>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <Input
            id="register-username"
            label="用户名"
            type="text"
            autoComplete="username"
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
            required
          />
          <Input
            id="register-email"
            label="邮箱"
            type="email"
            autoComplete="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            required
          />
          <Input
            id="register-password"
            label="密码"
            type="password"
            autoComplete="new-password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            required
          />
          {error && (
            <p role="alert" className="text-danger text-sm">
              {error}
            </p>
          )}
          <Button
            type="submit"
            className="w-full inline-flex items-center justify-center gap-2"
            disabled={submitting}
            aria-busy={submitting}
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
            {submitting ? '注册中…' : '注册'}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm">
          已有账号？{' '}
          <Link to="/login" className="text-primary hover:underline cursor-pointer">
            登录
          </Link>
        </p>
      </Card>
    </main>
  )
}
