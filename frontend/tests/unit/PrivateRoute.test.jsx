import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import PrivateRoute from '../../src/components/PrivateRoute'
import { RuntimeProfileContext } from '../../src/components/runtimeProfileContext'

const Protected = () => <div>protected</div>
const Login = () => <div>login-page</div>

const renderWithAuth = (token) => {
  if (token) {
    window.sessionStorage.setItem('auth_token', token)
  }
  return render(
    <RuntimeProfileContext.Provider value={{ profile: 'server', isLocal: false, requiresAuth: true, loading: false }}>
      <MemoryRouter
        initialEntries={['/dashboard']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route
            path="/dashboard"
            element={
              <PrivateRoute>
                <Protected />
              </PrivateRoute>
            }
          />
          <Route path="/login" element={<Login />} />
        </Routes>
      </MemoryRouter>
    </RuntimeProfileContext.Provider>
  )
}

describe('PrivateRoute', () => {
  it('renders children when authenticated', () => {
    renderWithAuth('abc')
    expect(screen.getByText('protected')).toBeTruthy()
  })

  it('redirects to /login when unauthenticated', () => {
    renderWithAuth(null)
    expect(screen.getByText('login-page')).toBeTruthy()
  })
})
