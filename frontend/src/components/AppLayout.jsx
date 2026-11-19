import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { BookOpen, CheckCircle, GraduationCap, LayoutGrid, LogOut } from 'lucide-react'
import { removeToken } from '../utils/auth'
import { useRuntimeProfile } from './runtimeProfileContext'
import ThemeToggle from './ThemeToggle'
import UpdateNotice from './UpdateNotice'

// Each workspace is a spine: cloth colour, vertical title and, for the two
// platforms, the platform name at the foot.
const SHELF = [
  { to: '/dashboard', title: '工作台', publisher: '', ariaLabel: '工作台', spine: 'home', icon: LayoutGrid, mobileLabel: '工作台', height: 'h-[13.5rem]' },
  { to: '/chaoxing-fanya', title: '课程学习', publisher: '学习通', ariaLabel: '学习通泛雅', spine: 'fanya', icon: BookOpen, mobileLabel: '学习通', height: 'h-[15.5rem]' },
  { to: '/chaoxing-signin', title: '课堂签到', publisher: '学习通', ariaLabel: '学习通签到', spine: 'signin', icon: CheckCircle, mobileLabel: '签到', height: 'h-[14.5rem]' },
  { to: '/zhihuishu-panel', title: '课程学习', publisher: '智慧树', ariaLabel: '智慧树', spine: 'zhihuishu', icon: GraduationCap, mobileLabel: '智慧树', height: 'h-[15rem]' },
]

function BrandMark({ className = '' }) {
  return (
    <span className={`relative grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded-md bg-[rgb(var(--spine-home))] text-on-spine ${className}`} aria-hidden="true">
      <BookOpen className="h-[18px] w-[18px]" />
      <span className="absolute inset-x-0 bottom-1 mx-auto h-[2px] w-5 bg-[rgb(var(--color-rule))]" />
    </span>
  )
}

export default function AppLayout() {
  const navigate = useNavigate()
  const { isLocal } = useRuntimeProfile()

  const handleLogout = () => {
    if (window.confirm('确定要退出学道吗？')) {
      removeToken()
      navigate('/login', { replace: true })
    }
  }

  const localBadge = isLocal && (
    <span className="inline-flex items-center gap-1 rounded-md border border-success/35 bg-success-surface px-2 py-1 text-xs font-semibold text-success">
      <span className="sm:hidden">本地</span>
      <span className="hidden sm:inline">本地模式</span>
    </span>
  )

  const logoutButton = !isLocal && (
    <button
      type="button"
      onClick={handleLogout}
      aria-label="退出登录"
      className="ui-btn-ghost min-h-[38px] px-3 hover:bg-danger-surface hover:text-danger"
    >
      <LogOut className="h-4 w-4" aria-hidden="true" />
      <span className="hidden sm:inline">退出</span>
    </button>
  )

  return (
    <div className="min-h-screen bg-background text-text lg:grid lg:grid-cols-[15rem_minmax(0,1fr)]">
      <a href="#main-content" className="skip-link fixed left-4 top-3 z-[100] rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-primary shadow-lg">
        跳到主要内容
      </a>

      {/* Wide screens: the shelf of spines. */}
      <aside className="sticky top-0 hidden h-[100dvh] flex-col border-r border-border bg-surface-hover/50 px-4 pb-5 pt-5 lg:flex">
        <NavLink to="/dashboard" aria-label="学道工作台" className="flex items-center gap-2.5 rounded-md">
          <BrandMark />
          <span className="font-display text-lg font-bold leading-none tracking-[0.24em] text-text">学道</span>
        </NavLink>

        <nav aria-label="主要导航" className="mt-8">
          <ul className="flex items-end gap-1.5 border-b-[6px] border-[rgb(var(--color-border))] pb-0 pt-4">
            {SHELF.map(({ to, title, publisher, ariaLabel, spine, height }) => (
              <li key={to}>
                <NavLink to={to} aria-label={ariaLabel} className={`spine spine-${spine} ${height}`}>
                  {({ isActive }) => (
                    <>
                      <span className="spine-band" aria-hidden="true" />
                      <span className="spine-title" aria-hidden="true">{title}</span>
                      <span className="flex flex-col items-center gap-1.5" aria-hidden="true">
                        <span className="spine-band w-5" />
                        {publisher && <span className="text-[0.625rem] font-semibold leading-none tracking-tight">{publisher}</span>}
                      </span>
                      {isActive && <span className="spine-ribbon" aria-hidden="true" />}
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

      </aside>

      <div className="flex min-w-0 flex-col">
        {/* One utility bar for every width: brand on narrow screens, then
            runtime mode, theme and session. */}
        <header className="sticky top-0 z-30 border-b border-border bg-background/95">
          <div className="mx-auto flex max-w-[80rem] items-center gap-3 px-4 py-2.5 sm:px-6 lg:px-8">
            <NavLink to="/dashboard" aria-label="学道工作台" className="flex min-w-0 items-center gap-2.5 lg:hidden">
              <BrandMark />
              <span className="font-display text-base font-bold leading-none tracking-[0.2em] text-text">学道</span>
            </NavLink>
            <div className="ml-auto flex items-center gap-1.5">
              {localBadge}
              <ThemeToggle />
              {logoutButton}
            </div>
          </div>
        </header>

        <main id="main-content" tabIndex="-1" className="min-w-0 flex-1 px-4 pb-28 pt-5 focus:outline-none sm:px-6 sm:pt-6 lg:px-8 lg:pb-10">
          <div className="mx-auto max-w-[76rem]"><Outlet /></div>
        </main>
      </div>

      <nav
        className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-background/95 px-2 pb-[max(0.375rem,env(safe-area-inset-bottom))] lg:hidden"
        aria-label="服务切换"
      >
        <ul className="mx-auto grid max-w-lg grid-cols-4 gap-1">
          {SHELF.map(({ to, mobileLabel, ariaLabel, spine, icon: Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                aria-label={ariaLabel}
                className={({ isActive }) => `spine-${spine} flex min-h-[54px] flex-col items-center justify-center gap-1 rounded-b-md px-1 pt-1 text-xs font-semibold ${
                  isActive ? 'text-text' : 'text-text-muted hover:text-text'
                }`}
              >
                {({ isActive }) => (
                  <>
                    <span
                      aria-hidden="true"
                      className={`block w-full rounded-b-sm transition-[height] ${isActive ? 'h-1' : 'h-px opacity-60'}`}
                      style={{ background: 'rgb(var(--spine))' }}
                    />
                    <Icon className="h-4 w-4" aria-hidden="true" />
                    <span>{mobileLabel}</span>
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      {!isLocal && <UpdateNotice />}
    </div>
  )
}
