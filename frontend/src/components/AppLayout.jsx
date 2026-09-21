import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { BookOpen, CheckCircle, GraduationCap, LayoutGrid, LogOut } from 'lucide-react'
import { removeToken } from '../utils/auth'
import { useRuntimeProfile } from './runtimeProfileContext'
import ThemeToggle from './ThemeToggle'
import UpdateNotice from './UpdateNotice'

const NAV = [
  { to: '/dashboard', label: '工作台', shortLabel: '总览', icon: LayoutGrid },
  { to: '/chaoxing-signin', label: '学习通签到', shortLabel: '签到', icon: CheckCircle },
  { to: '/chaoxing-fanya', label: '学习通泛雅', shortLabel: '泛雅', icon: BookOpen },
  { to: '/zhihuishu-panel', label: '智慧树', shortLabel: '智慧树', icon: GraduationCap },
]

const desktopLinkClass = ({ isActive }) =>
  `inline-flex min-h-[42px] items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold ${
    isActive
      ? 'bg-primary/10 text-primary shadow-[inset_0_-2px_0_rgb(var(--color-primary))]'
      : 'text-text-muted hover:bg-surface-hover hover:text-text'
  }`

export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { isLocal } = useRuntimeProfile()

  const handleLogout = () => {
    if (window.confirm('确定要退出学道吗？')) {
      removeToken()
      navigate('/login', { replace: true })
    }
  }

  return (
    <div className="min-h-screen bg-background text-text">
      <a
        href="#main-content"
        className="skip-link fixed left-4 top-3 z-[100] rounded-lg bg-secondary px-4 py-2 text-sm font-semibold text-background shadow-lg"
      >
        跳到主要内容
      </a>

      <header className="sticky top-0 z-30 border-b border-border/80 bg-background/95 supports-[backdrop-filter]:bg-background/85 supports-[backdrop-filter]:backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3 sm:px-6">
          <NavLink
            to="/dashboard"
            aria-label="学道工作台"
            className="group flex shrink-0 items-center gap-2.5"
          >
            <span className="relative grid h-10 w-10 place-items-center overflow-hidden rounded-xl bg-secondary text-background shadow-sm dark:text-text">
              <BookOpen className="h-5 w-5" aria-hidden="true" />
              <span className="absolute bottom-0 right-0 h-2.5 w-2.5 bg-cta" aria-hidden="true" />
            </span>
            <span className="text-lg font-black leading-none tracking-[0.18em] text-text">学道</span>
          </NavLink>

          <nav className="ml-2 hidden items-center gap-1 md:flex" aria-label="主要导航">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} className={desktopLinkClass}>
                <Icon className="h-4 w-4" aria-hidden="true" />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            {isLocal && (
              <span className="inline-flex rounded-full border border-success/25 bg-success-surface px-2 py-1 text-[11px] font-semibold text-success sm:px-2.5 sm:text-xs">
                <span className="sm:hidden">本地</span>
                <span className="hidden sm:inline">本地模式</span>
              </span>
            )}
            <ThemeToggle />
            {!isLocal && (
              <button
                type="button"
                onClick={handleLogout}
                aria-label="退出登录"
                className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border border-border bg-surface px-3 text-sm font-semibold text-text-muted hover:border-danger/30 hover:bg-danger-surface hover:text-danger"
              >
                <LogOut className="h-4 w-4" aria-hidden="true" />
                <span className="hidden sm:inline">退出</span>
              </button>
            )}
          </div>
        </div>

        <nav className="border-t border-border-subtle px-2 py-1.5 md:hidden" aria-label="服务切换">
          <div className="mx-auto grid max-w-lg grid-cols-4 gap-1">
            {NAV.map(({ to, label, shortLabel, icon: Icon }) => {
              const active = location.pathname === to
              return (
                <NavLink
                  key={to}
                  to={to}
                  aria-label={label}
                  aria-current={active ? 'page' : undefined}
                  className={`flex min-h-[48px] flex-col items-center justify-center gap-1 rounded-lg px-1 text-[11px] font-semibold ${
                    active ? 'bg-primary/10 text-primary' : 'text-text-muted hover:bg-surface-hover hover:text-text'
                  }`}
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />
                  <span>{shortLabel}</span>
                </NavLink>
              )
            })}
          </div>
        </nav>
      </header>

      <main id="main-content" tabIndex="-1" className="mx-auto max-w-7xl px-4 py-6 focus:outline-none sm:px-6 sm:py-8">
        <Outlet />
      </main>
      {!isLocal && <UpdateNotice />}
    </div>
  )
}
