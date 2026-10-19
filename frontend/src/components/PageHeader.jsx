// One header shape for every workspace page: platform eyebrow, title, an
// optional one-line hint, right-aligned actions (account chip, running-task
// shortcut), and the page's tabs underneath.
export default function PageHeader({ eyebrow, title, description, actions, children }) {
  return (
    <header className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          {eyebrow && <p className="text-xs font-semibold text-primary">{eyebrow}</p>}
          <h1 className="mt-1 text-2xl font-bold text-text">{title}</h1>
          {description && <p className="mt-1 text-sm text-text-muted">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </header>
  )
}
