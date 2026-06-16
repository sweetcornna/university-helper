import { Input } from '../../../components'
import { CARD } from '../utils'

export default function LoginSection({
  username,
  setUsername,
  password,
  setPassword,
  loginLoading,
  handleLogin,
}) {
  return (
    <section className={CARD}>
      <h2 className="mb-4 text-xl font-semibold text-text">登录账号</h2>

      <form className="grid gap-4 md:grid-cols-2" onSubmit={handleLogin} noValidate>
        <Input
          id="fanya-username"
          label="超星账号"
          name="cx-username"
          autoComplete="username"
          placeholder="请输入超星账号"
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
          placeholder="请输入密码"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />

        <button
          type="submit"
          disabled={loginLoading}
          aria-busy={loginLoading}
          className="min-h-[44px] cursor-pointer rounded-xl bg-primary px-6 py-3 font-medium text-white transition duration-200 hover:bg-primary/90 disabled:cursor-not-allowed disabled:bg-text-muted md:col-span-2"
        >
          {loginLoading ? '登录中...' : '登录并获取课程'}
        </button>
      </form>
    </section>
  )
}
