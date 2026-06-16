import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, expect, test } from 'vitest'

import { AppLayout, ThemeProvider, ToastProvider } from './components'
import Dashboard from './pages/Dashboard'

// Smoke test: the full provider stack + shell + redesigned dashboard mount
// without throwing, dark-mode wiring runs, and key chrome renders.
describe('app shell smoke', () => {
  test('AppLayout + Dashboard render inside the providers', () => {
    render(
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={['/dashboard']}>
            <Routes>
              <Route element={<AppLayout />}>
                <Route path="/dashboard" element={<Dashboard />} />
              </Route>
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>
    )

    // AppLayout brand + nav
    expect(screen.getAllByText('刷课平台').length).toBeGreaterThan(0)
    // Dashboard heading (unique to the home page)
    expect(screen.getByText('选择服务')).toBeTruthy()
    // Service entries appear in both the nav and the cards
    expect(screen.getAllByText('学习通签到').length).toBeGreaterThan(0)
    expect(screen.getAllByText('智慧树').length).toBeGreaterThan(0)
    // Theme toggle is present (radiogroup)
    expect(screen.getByRole('radiogroup', { name: '主题' })).toBeTruthy()
  })
})
