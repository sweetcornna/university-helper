import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <main className="min-h-screen flex items-center justify-center p-6 bg-background">
      <div className="text-center space-y-4">
        <p className="text-7xl font-bold text-primary tracking-tight">404</p>
        <h1 className="text-xl font-semibold text-text">页面不存在</h1>
        <p className="text-sm text-text-muted">你访问的链接可能已失效或被移动。</p>
        <Link
          to="/"
          className="inline-block px-4 py-2 rounded-lg bg-primary text-white hover:opacity-90"
        >
          返回首页
        </Link>
      </div>
    </main>
  )
}
