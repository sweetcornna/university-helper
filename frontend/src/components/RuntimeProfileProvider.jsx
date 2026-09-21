import { useCallback, useEffect, useMemo, useState } from 'react'
import { setApiRuntimeProfile } from '../utils/api'
import { RuntimeProfileContext } from './runtimeProfileContext'

const SERVER_PROFILE = Object.freeze({
  profile: 'server',
  isLocal: false,
  requiresAuth: true,
})

// Keep capability discovery on the same 20s budget as the default API client
// timeout, so a stalled endpoint cannot keep the app in its loading route.
const RUNTIME_PROFILE_TIMEOUT_MS = 20_000

const normalizeRuntimeProfile = (payload) => {
  if (payload?.profile !== 'local') return SERVER_PROFILE
  return {
    profile: 'local',
    isLocal: true,
    requiresAuth: false,
  }
}

export default function RuntimeProfileProvider({ children }) {
  const [state, setState] = useState({ ...SERVER_PROFILE, loading: true })

  useEffect(() => {
    const controller = new AbortController()
    let mounted = true
    let timedOut = false

    const failClosed = () => {
      if (!mounted) return
      setApiRuntimeProfile('server')
      setState({ ...SERVER_PROFILE, loading: false })
    }

    const timeoutId = setTimeout(() => {
      timedOut = true
      clearTimeout(timeoutId)
      controller.abort()
      failClosed()
    }, RUNTIME_PROFILE_TIMEOUT_MS)

    const loadRuntimeProfile = async () => {
      try {
        const response = await fetch('/api/v1/runtime', {
          headers: { Accept: 'application/json' },
          signal: controller.signal,
        })
        if (!response.ok) throw new Error(`Runtime profile request failed (${response.status})`)
        const profile = normalizeRuntimeProfile(await response.json())
        if (!mounted || timedOut) return
        setApiRuntimeProfile(profile.profile)
        setState({ ...profile, loading: false })
      } catch (error) {
        if (mounted && !timedOut && error?.name !== 'AbortError') {
          // A failed capability request must never turn a server deployment into
          // an unauthenticated client. Keep the default server policy.
          failClosed()
        }
      } finally {
        clearTimeout(timeoutId)
      }
    }

    void loadRuntimeProfile()
    return () => {
      mounted = false
      controller.abort()
      clearTimeout(timeoutId)
    }
  }, [])

  // Register/login answer 409 LocalProfileAuthUnavailable only on the desktop
  // build. That is as authoritative as /api/v1/runtime, so a page that receives
  // it can switch to local mode even when capability discovery itself failed.
  const markLocal = useCallback(() => {
    setApiRuntimeProfile('local')
    setState({ ...normalizeRuntimeProfile({ profile: 'local' }), loading: false })
  }, [])

  const value = useMemo(() => ({ ...state, markLocal }), [state, markLocal])

  return (
    <RuntimeProfileContext.Provider value={value}>
      {children}
    </RuntimeProfileContext.Provider>
  )
}
