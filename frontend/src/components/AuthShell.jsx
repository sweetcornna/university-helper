import { Link } from 'react-router-dom'
import { BookOpen } from 'lucide-react'
import ThemeToggle from './ThemeToggle'

// Shared frame for 登录 / 注册: one index card holding the brand and the form.
export default function AuthShell({ homeTo, homeLabel, title, children, footer }) {
  return (
    <main className="relative min-h-screen bg-background">
      <div className="absolute right-4 top-4 z-20"><ThemeToggle /></div>
      <div className="mx-auto flex min-h-screen w-full max-w-[25rem] flex-col justify-center px-4 py-16">
        <div className="ui-index-card px-5 pb-6 pt-7 sm:px-7">
          <Link to={homeTo} className="mb-6 flex w-fit items-center gap-2.5 rounded-md" aria-label={homeLabel}>
            <span className="relative grid h-10 w-10 place-items-center overflow-hidden rounded-md bg-[rgb(var(--spine-home))] text-on-spine" aria-hidden="true">
              <BookOpen className="h-5 w-5" />
              <span className="absolute inset-x-0 bottom-1 mx-auto h-[2px] w-5 bg-[rgb(var(--color-rule))]" />
            </span>
            <span className="font-display text-xl font-bold tracking-[0.2em] text-text">学道</span>
          </Link>
          <h1 className="font-display text-2xl font-bold text-text">{title}</h1>
          {children}
        </div>
        {footer && <div className="mt-4 text-center text-sm text-text-muted">{footer}</div>}
      </div>
    </main>
  )
}
