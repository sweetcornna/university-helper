import { Navigate, useLocation } from 'react-router-dom'
import { isAuthenticated } from '../utils/auth'
import { useRuntimeProfile } from './runtimeProfileContext'

export default function PrivateRoute({ children }) {
  const location = useLocation()
  const { isLocal } = useRuntimeProfile()

  if (!isLocal && !isAuthenticated()) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }
  return children
}
