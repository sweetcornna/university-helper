// Page header: platform label in its spine colour, display title, optional
// short status line, right-aligned actions and the page's index tabs.
export default function PageHeader({ eyebrow, title, description, actions, children, spine = 'home' }) {
  return (
    <header className={`spine-${spine} space-y-4`}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          {eyebrow && (
            <p className="catalog-label flex items-center gap-2">
              <span className="spine-chip" aria-hidden="true" />
              {eyebrow}
            </p>
          )}
          <h1 className="font-display mt-1 text-[1.375rem] font-bold leading-tight text-text sm:text-2xl">{title}</h1>
          {description && <p className="mt-1 max-w-2xl text-sm text-text-muted">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </header>
  )
}
