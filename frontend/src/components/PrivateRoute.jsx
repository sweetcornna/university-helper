import { Navigate, useLocation } from 'react-router-dom'
import { isAuthenticated } from '../utils/auth'

export default function PrivateRoute({ children }) {
  const location = useLocation()
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return children
}
