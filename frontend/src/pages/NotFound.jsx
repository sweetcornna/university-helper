import { Link } from 'react-router-dom'
import { ThemeToggle } from '../components'

export default function NotFound() {
  return (
    <main className="relative flex min-h-screen items-center justify-center bg-background p-6">
      <div className="absolute right-4 top-4"><ThemeToggle /></div>
      <div className="ui-index-card w-full max-w-sm px-6 pb-6 pt-7">
        <h1 className="font-display text-xl font-bold text-text">
          <span className="font-code text-text-muted">404</span>{' '}页面不存在
        </h1>
        <Link to="/" className="ui-btn-primary mt-5">
          返回首页
        </Link>
      </div>
    </main>
  )
}
