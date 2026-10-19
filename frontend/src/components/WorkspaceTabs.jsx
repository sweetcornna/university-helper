import { useRef } from 'react'
import { Link, useLocation } from 'react-router-dom'

export default function WorkspaceTabs({ id, label, tabs, activeTab, onChange }) {
  const location = useLocation()
  const tabRefs = useRef({})

  const handleKeyDown = (event) => {
    const currentIndex = tabs.findIndex((tab) => tabRefs.current[tab.id] === event.target)
    if (currentIndex < 0) return

    let nextIndex
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') nextIndex = (currentIndex + 1) % tabs.length
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') nextIndex = (currentIndex - 1 + tabs.length) % tabs.length
    else if (event.key === 'Home') nextIndex = 0
    else if (event.key === 'End') nextIndex = tabs.length - 1
    else return

    event.preventDefault()
    const nextTab = tabs[nextIndex].id
    onChange(nextTab)
    tabRefs.current[nextTab]?.focus()
  }

  return (
    <div
      role="tablist"
      tabIndex="-1"
      aria-label={label}
      onKeyDown={handleKeyDown}
      className="scrollbar-none flex gap-1 overflow-x-auto shadow-[inset_0_-1px_0_rgb(var(--color-border))]"
    >
      {tabs.map((tab) => {
        const search = new URLSearchParams(location.search)
        search.set('tab', tab.id)
        const active = activeTab === tab.id
        return (
          <Link
            key={tab.id}
            ref={(element) => { tabRefs.current[tab.id] = element }}
            to={{ pathname: location.pathname, search: `?${search}`, hash: location.hash }}
            id={`${id}-tab-${tab.id}`}
            role="tab"
            aria-selected={active}
            aria-controls={`${id}-panel-${tab.id}`}
            tabIndex={active ? 0 : -1}
            onClick={(event) => {
              if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
              event.preventDefault()
              onChange(tab.id)
            }}
            className={`inline-flex min-h-[44px] shrink-0 items-center justify-center gap-2 border-b-2 px-3 text-sm font-semibold sm:px-4 ${
              active ? 'border-primary text-primary' : 'border-transparent text-text-muted hover:border-border hover:text-text'
            }`}
          >
            {tab.label}
            {tab.count > 0 && (
              <span className="rounded-full bg-primary/10 px-1.5 text-xs text-primary">
                {tab.count}
              </span>
            )}
          </Link>
        )
      })}
    </div>
  )
}
