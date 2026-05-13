import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthExpiredListener, ErrorBoundary, PrivateRoute, RouteFallback } from './components'

const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const ChaoxingSignin = lazy(() => import('./pages/ChaoxingSignin'))
const ChaoxingFanya = lazy(() => import('./pages/ChaoxingFanya'))
const Zhihuishu = lazy(() => import('./pages/Zhihuishu'))
const NotFound = lazy(() => import('./pages/NotFound'))

function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AuthExpiredListener />
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route
              path="/dashboard"
              element={<PrivateRoute><Dashboard /></PrivateRoute>}
            />
            <Route
              path="/chaoxing-signin"
              element={<PrivateRoute><ChaoxingSignin /></PrivateRoute>}
            />
            <Route
              path="/chaoxing-fanya"
              element={<PrivateRoute><ChaoxingFanya /></PrivateRoute>}
            />
            <Route
              path="/zhihuishu-panel"
              element={<PrivateRoute><Zhihuishu /></PrivateRoute>}
            />
            <Route path="/" element={<Navigate to="/login" replace />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </ErrorBoundary>
  )
}

export default App
