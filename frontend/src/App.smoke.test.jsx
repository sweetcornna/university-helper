import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, expect, test } from 'vitest'

import { AppLayout, ThemeProvider, ToastProvider } from './components'
import { RuntimeProfileContext } from './components/runtimeProfileContext'
import Dashboard from './pages/Dashboard'

// Smoke test: the full provider stack + shell + redesigned dashboard mount
// without throwing, dark-mode wiring runs, and key chrome renders.
describe('app shell smoke', () => {
  test('AppLayout + Dashboard render inside the providers', () => {
    render(
      <ThemeProvider>
        <RuntimeProfileContext.Provider
          value={{ profile: 'server', isLocal: false, requiresAuth: true, loading: false }}
        >
          <ToastProvider>
            <MemoryRouter
              initialEntries={['/dashboard']}
              future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
            >
              <Routes>
                <Route element={<AppLayout />}>
                  <Route path="/dashboard" element={<Dashboard />} />
                </Route>
              </Routes>
            </MemoryRouter>
          </ToastProvider>
        </RuntimeProfileContext.Provider>
      </ThemeProvider>
    )

    // AppLayout brand + nav
    expect(screen.getAllByText('学道').length).toBeGreaterThan(0)
    // Dashboard heading (unique to the home page)
    expect(screen.getByRole('heading', { level: 1, name: '今日任务' })).toBeTruthy()
    // Service entries appear in both the nav and the cards
    expect(screen.getAllByText('学习通签到').length).toBeGreaterThan(0)
    expect(screen.getAllByText('智慧树').length).toBeGreaterThan(0)
    // Theme toggle is present (radiogroup)
    expect(screen.getByRole('radiogroup', { name: '主题' })).toBeTruthy()
  })
})
