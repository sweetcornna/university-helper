import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'

const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const ChaoxingSignin = lazy(() => import('./pages/ChaoxingSignin'))
const ChaoxingFanya = lazy(() => import('./pages/ChaoxingFanya'))
const Zhihuishu = lazy(() => import('./pages/Zhihuishu'))

function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<div className="flex items-center justify-center min-h-screen">Loading…</div>}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/chaoxing-signin" element={<ChaoxingSignin />} />
          <Route path="/chaoxing-fanya" element={<ChaoxingFanya />} />
          <Route path="/zhihuishu-panel" element={<Zhihuishu />} />
          <Route path="/" element={<Navigate to="/login" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}

export default App
