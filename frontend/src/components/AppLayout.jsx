import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { BookOpen, CheckCircle, GraduationCap, LayoutGrid, LogOut } from 'lucide-react'
import { removeToken } from '../utils/auth'
import ThemeToggle from './ThemeToggle'

const NAV = [
  { to: '/dashboard', label: '首页', icon: LayoutGrid },
  { to: '/chaoxing-signin', label: '学习通签到', icon: CheckCircle },
  { to: '/chaoxing-fanya', label: '学习通泛雅', icon: BookOpen },
  { to: '/zhihuishu-panel', label: '智慧树', icon: GraduationCap },
]

const linkClass = ({ isActive }) =>
  `inline-flex min-h-[40px] items-center gap-1.5 whitespace-nowrap rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors ${
    isActive ? 'bg-primary text-white' : 'text-text/70 hover:bg-surface-hover'
  }`

/*
 * Persistent app shell shared by every authenticated page. Previously each page
 * hand-rolled its own header, background and "返回" button, with no way to jump
 * between services without going back to the home screen and no consistent
 * logout. This Outlet layout owns brand, service switching, theme and logout.
 */
export default function AppLayout() {
  const navigate = useNavigate()

  const handleLogout = () => {
    if (window.confirm('确定要退出登录吗？')) {
      removeToken()
      navigate('/login', { replace: true })
    }
  }

  return (
    <div className="min-h-screen bg-background text-text">
      <header className="sticky top-0 z-30 border-b border-border/60 bg-surface/80 backdrop-blur-lg">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3">
          <NavLink
            to="/dashboard"
            className="flex shrink-0 items-center gap-2 text-base font-bold tracking-tight text-text"
          >
            刷课平台
          </NavLink>

          <nav className="ml-2 hidden items-center gap-1 lg:flex">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} className={linkClass}>
                <Icon className="h-4 w-4" aria-hidden="true" />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            <button
              type="button"
              onClick={handleLogout}
              aria-label="退出登录"
              className="inline-flex min-h-[40px] items-center gap-1.5 rounded-full border border-border/60 bg-surface/60 px-3.5 py-1.5 text-sm text-text/70 transition-colors hover:bg-surface-hover hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
            >
              <LogOut className="h-4 w-4" aria-hidden="true" />
              <span className="hidden sm:inline">退出</span>
            </button>
          </div>
        </div>

        {/* Mobile / tablet: scrollable service switcher */}
        <nav className="flex gap-1 overflow-x-auto px-4 pb-2 lg:hidden">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={linkClass}>
              <Icon className="h-4 w-4" aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
