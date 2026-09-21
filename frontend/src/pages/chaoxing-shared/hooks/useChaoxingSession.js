import { useCallback, useEffect, useRef, useState } from 'react'

import { SESSION_LOST_MESSAGE, isChaoxingSessionLost } from '../utils'

// Session states. 'probing' → the mount-time GET /chaoxing/session is still in
// flight; 'active' → the server confirmed a session, so no password is needed;
// 'inactive' → no session, OR the probe failed / timed out. Anything other than
// a confirmed session falls back to the credential form, so a backend without
// these endpoints leaves the page exactly as it was.
const PROBING = 'probing'
const ACTIVE = 'active'
const INACTIVE = 'inactive'

/**
 * Tracks whether the SERVER holds a usable Chaoxing session for this user.
 *
 * This is what makes "log in once" work: the session is stored server-side
 * (encrypted, 7-day rolling TTL) and shared by the 签到 and 泛雅 pages, so a
 * login on one page is not re-asked for on the other.
 *
 * @param request  `(path, options) => Promise<payload>` — the calling page's
 *                 authenticated fetch wrapper. Both pages have their own, so it
 *                 is injected rather than imported.
 */
export default function useChaoxingSession({ request }) {
  const [sessionStatus, setSessionStatus] = useState(PROBING)
  const [sessionUsername, setSessionUsername] = useState('')
  const [sessionExpiresAt, setSessionExpiresAt] = useState('')
  const [switchLoading, setSwitchLoading] = useState(false)

  // Keeps the probe to exactly one request for the component's lifetime, even
  // if the callbacks below are re-created (and under StrictMode's double-invoked
  // effects).
  const probedRef = useRef(false)

  useEffect(() => {
    if (probedRef.current) return
    probedRef.current = true

    const probe = async () => {
      try {
        const resp = await request('/session', { timeoutMs: 8000 })
        if (resp?.active) {
          setSessionUsername(String(resp.username || '').trim())
          setSessionExpiresAt(String(resp.expires_at || ''))
          setSessionStatus(ACTIVE)
          return
        }
        setSessionStatus(INACTIVE)
      } catch {
        // Fail open. A backend without /chaoxing/session, a timeout, or a 200
        // carrying the SPA's index.html (the backend serves that for any
        // unmatched GET, so a missing route is NOT a 404) must all land on the
        // credential form.
        setSessionStatus(INACTIVE)
      }
    }

    // Deliberately no `cancelled` flag. `probedRef` already guarantees exactly
    // one probe for the component's lifetime, so a cancel-on-unmount guard
    // would discard the ONLY result: StrictMode mounts, unmounts (cancel), then
    // remounts, and the remounted effect returns early on the ref — leaving
    // sessionStatus stuck on 'probing' forever and the login form never shown.
    void probe()
  }, [request])

  // A fresh login — password or QR — IS the session. Recording it here lets the
  // form give way to the status line immediately, without waiting for a probe.
  const adoptSession = useCallback((username, expiresAt = '') => {
    setSessionUsername(String(username || '').trim())
    setSessionExpiresAt(String(expiresAt || ''))
    setSessionStatus(ACTIVE)
  }, [])

  // The server-side session died mid-use (expired upstream, or revoked).
  const markSessionLost = useCallback(() => {
    setSessionStatus(INACTIVE)
    setSessionUsername('')
    setSessionExpiresAt('')
  }, [])

  // The "切换账号" action: forget the server session and come back to the form
  // even when the server can't be reached, so the button never looks stuck.
  const switchAccount = useCallback(async () => {
    setSwitchLoading(true)
    try {
      await request('/session', { method: 'DELETE' })
      return { ok: true }
    } catch (err) {
      return { ok: false, error: err?.message || '退出登录失败，重新登录将覆盖当前会话。' }
    } finally {
      setSessionStatus(INACTIVE)
      setSessionUsername('')
      setSessionExpiresAt('')
      setSwitchLoading(false)
    }
  }, [request])

  return {
    // True only once the server has confirmed, so callers never treat a failed
    // probe as a login.
    authenticated: sessionStatus === ACTIVE,
    sessionStatus,
    sessionUsername,
    sessionExpiresAt,
    switchLoading,
    adoptSession,
    markSessionLost,
    switchAccount,
    isChaoxingSessionLost,
    SESSION_LOST_MESSAGE,
  }
}
