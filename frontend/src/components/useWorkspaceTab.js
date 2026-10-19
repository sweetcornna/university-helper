import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

// Keep the existing page paths while making each workspace shareable. The
// remaining query parameters belong to the caller and must survive tab changes.
export default function useWorkspaceTab(tabs, defaultTab, aliases = {}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab')
  const resolvedTab = aliases[requestedTab] || requestedTab
  const activeTab = tabs.some((tab) => tab.id === resolvedTab) ? resolvedTab : defaultTab

  const setActiveTab = useCallback((tab, options = {}) => {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous)
      next.set('tab', tab)
      return next
    }, options)
  }, [setSearchParams])

  return [activeTab, setActiveTab]
}
