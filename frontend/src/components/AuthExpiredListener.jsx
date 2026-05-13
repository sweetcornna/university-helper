import { useEffect, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { AUTH_EXPIRED_EVENT } from '../utils/api'

export default function AuthExpiredListener() {
  const navigate = useNavigate()
  const location = useLocation()
  // Stash the latest location in a ref so a single, stable subscription
  // can still recover the "from" path at fire-time. Otherwise every
  // navigation re-runs add/removeEventListener.
  const locationRef = useRef(location)
  useEffect(() => {
    locationRef.current = location
  })

  useEffect(() => {
    const handler = () => {
      const loc = locationRef.current
      navigate('/login', {
        replace: true,
        state: { from: loc.pathname + loc.search },
      })
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, handler)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handler)
  }, [navigate])

  return null
}
