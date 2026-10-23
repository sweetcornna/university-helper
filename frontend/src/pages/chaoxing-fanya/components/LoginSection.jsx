import { Input } from '../../../components'
import { translateTaskMessage } from '../../../utils/taskMessages'
import { CARD } from '../utils'

export default function LoginSection({
  username,
  setUsername,
  password,
  setPassword,
  loginLoading,
  handleLogin,
  loginError = '',
}) {
  return (
    <section aria-labelledby="fanya-login-title" className={CARD}>
      <h2 id="fanya-login-title" className="text-lg font-semibold text-text">登录学习通</h2>
      <p className="mb-4 mt-1 text-sm text-text-muted">登录后会自动读取课程。密码只在本页使用，不会保存。</p>

      <form className="grid gap-4 md:grid-cols-2" onSubmit={handleLogin} noValidate>
        <Input
          id="fanya-username"
          label="超星账号"
          name="cx-username"
          autoComplete="username"
          disabled={loginLoading}
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          required
        />

        <Input
          id="fanya-password"
          label="密码"
          type="password"
          name="cx-password"
          autoComplete="current-password"
          disabled={loginLoading}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />

        {loginError && (
          <p role="alert" className="rounded-xl border border-danger/30 bg-danger-surface px-3 py-2.5 text-sm text-danger md:col-span-2">
            {translateTaskMessage(loginError)}。请检查账号和密码；如果学习通要求验证码，先在学习通 App 里登录一次再试。
          </p>
        )}

        <button
          type="submit"
          disabled={loginLoading}
          aria-busy={loginLoading}
          className="clay-button-primary min-h-[48px] md:col-span-2"
        >
          {loginLoading ? '登录中...' : '登录并获取课程'}
        </button>
      </form>
    </section>
  )
}
