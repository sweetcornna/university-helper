import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import {
  AppLayout,
  AuthExpiredListener,
  ErrorBoundary,
  PrivateRoute,
  RouteFallback,
  ThemeProvider,
  ToastProvider,
} from './components'
import { isAuthenticated } from './utils/auth'

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
      <ThemeProvider>
        <BrowserRouter>
          <ToastProvider>
          <AuthExpiredListener />
          <Suspense fallback={<RouteFallback />}>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />
              <Route
                element={
                  <PrivateRoute>
                    <AppLayout />
                  </PrivateRoute>
                }
              >
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/chaoxing-signin" element={<ChaoxingSignin />} />
                <Route path="/chaoxing-fanya" element={<ChaoxingFanya />} />
                <Route path="/zhihuishu-panel" element={<Zhihuishu />} />
              </Route>
              <Route
                path="/"
                element={<Navigate to={isAuthenticated() ? '/dashboard' : '/login'} replace />}
              />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
          </ToastProvider>
        </BrowserRouter>
      </ThemeProvider>
    </ErrorBoundary>
  )
}

export default App
