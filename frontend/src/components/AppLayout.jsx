import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { BookOpen, CheckCircle, GraduationCap, LayoutGrid, LogOut } from 'lucide-react'
import { removeToken } from '../utils/auth'
import { useRuntimeProfile } from './runtimeProfileContext'
import ThemeToggle from './ThemeToggle'
import UpdateNotice from './UpdateNotice'

const NAV_GROUPS = [
  {
    label: '工作空间',
    links: [{ to: '/dashboard', label: '工作台', icon: LayoutGrid }],
  },
  {
    label: '学习通',
    links: [
      { to: '/chaoxing-fanya', label: '课程学习', ariaLabel: '学习通泛雅', icon: BookOpen },
      { to: '/chaoxing-signin', label: '课堂签到', ariaLabel: '学习通签到', icon: CheckCircle },
    ],
  },
  {
    label: '智慧树',
    links: [{ to: '/zhihuishu-panel', label: '课程学习', ariaLabel: '智慧树', icon: GraduationCap }],
  },
]

const MOBILE_NAV = [
  { to: '/dashboard', label: '工作台', icon: LayoutGrid },
  { to: '/chaoxing-fanya', label: '学习通', icon: BookOpen },
  { to: '/chaoxing-signin', label: '签到', icon: CheckCircle },
  { to: '/zhihuishu-panel', label: '智慧树', icon: GraduationCap },
]

const desktopLinkClass = ({ isActive }) =>
  `flex min-h-[44px] items-center gap-3 rounded-xl px-3 py-2 text-sm font-semibold ${
    isActive ? 'bg-primary/10 text-primary' : 'text-text-muted hover:bg-surface-hover hover:text-text'
  }`

export default function AppLayout() {
  const navigate = useNavigate()
  const { isLocal } = useRuntimeProfile()

  const handleLogout = () => {
    if (window.confirm('确定要退出学道吗？')) {
      removeToken()
      navigate('/login', { replace: true })
    }
  }

  return (
    <div className="min-h-screen bg-background text-text">
      <a href="#main-content" className="skip-link fixed left-4 top-3 z-[100] rounded-lg bg-secondary px-4 py-2 text-sm font-semibold text-background shadow-lg">
        跳到主要内容
      </a>

      <header className="sticky top-0 z-30 border-b border-border/80 bg-background/95 supports-[backdrop-filter]:bg-background/85 supports-[backdrop-filter]:backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1600px] items-center gap-4 px-4 py-3 sm:px-6">
          <NavLink to="/dashboard" aria-label="学道工作台" className="flex shrink-0 items-center gap-2.5">
            <span className="relative grid h-10 w-10 place-items-center overflow-hidden rounded-xl bg-secondary text-background shadow-sm dark:text-text">
              <BookOpen className="h-5 w-5" aria-hidden="true" />
              <span className="absolute bottom-0 right-0 h-2.5 w-2.5 bg-cta" aria-hidden="true" />
            </span>
            <span className="text-lg font-black leading-none tracking-[0.18em] text-text">学道</span>
          </NavLink>
          <div className="ml-auto flex items-center gap-2">
            {isLocal && <span className="rounded-full border border-success/25 bg-success-surface px-2 py-1 text-xs font-semibold text-success"><span className="sm:hidden">本地</span><span className="hidden sm:inline">本地模式</span></span>}
            <ThemeToggle />
            {!isLocal && (
              <button type="button" onClick={handleLogout} aria-label="退出登录" className="inline-flex min-h-[40px] items-center gap-1.5 rounded-xl border border-border bg-surface px-3 text-sm font-semibold text-text-muted hover:border-danger/30 hover:bg-danger-surface hover:text-danger">
                <LogOut className="h-4 w-4" aria-hidden="true" />
                <span className="hidden sm:inline">退出</span>
              </button>
            )}
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-[1600px]">
        <aside className="sticky top-[65px] hidden h-[calc(100dvh-65px)] w-52 shrink-0 flex-col border-r border-border px-4 py-6 lg:flex">
          <nav aria-label="主要导航" className="space-y-6">
            {NAV_GROUPS.map((group) => (
              <div key={group.label}>
                <p className="mb-2 px-3 text-xs font-semibold text-text-muted">{group.label}</p>
                <div className="space-y-1">
                  {group.links.map(({ to, label, ariaLabel, icon: Icon }) => (
                    <NavLink key={to} to={to} aria-label={ariaLabel} className={desktopLinkClass}>
                      <Icon className="h-4 w-4" aria-hidden="true" />{label}
                    </NavLink>
                  ))}
                </div>
              </div>
            ))}
          </nav>
        </aside>

        <main id="main-content" tabIndex="-1" className="min-w-0 flex-1 px-4 py-6 pb-28 focus:outline-none sm:px-6 sm:py-8 sm:pb-28 lg:pb-8">
          <div className="mx-auto max-w-6xl"><Outlet /></div>
        </main>
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-background/95 px-2 pt-1.5 pb-[max(0.5rem,env(safe-area-inset-bottom))] backdrop-blur-xl lg:hidden" aria-label="服务切换">
        <div className="mx-auto grid max-w-lg grid-cols-4 gap-1">
          {MOBILE_NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => `flex min-h-[52px] flex-col items-center justify-center gap-1 rounded-lg px-1 text-xs font-semibold ${isActive ? 'bg-primary/10 text-primary' : 'text-text-muted hover:bg-surface-hover hover:text-text'}`}>
              <Icon className="h-4 w-4" aria-hidden="true" /><span>{label}</span>
            </NavLink>
          ))}
        </div>
      </nav>
      {!isLocal && <UpdateNotice />}
    </div>
  )
}
