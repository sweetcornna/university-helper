import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'

import { ToastProvider } from '../components'
import { RuntimeProfileContext } from '../components/runtimeProfileContext'
import { api, ApiError, SERVER_ERROR_MESSAGE } from '../utils/api'
import Register from './Register'

vi.mock('../utils/api', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, api: vi.fn() }
})

const renderRegister = (runtime) =>
  render(
    <RuntimeProfileContext.Provider value={runtime}>
      <ToastProvider>
        <MemoryRouter initialEntries={['/register']}>
          <Routes>
            <Route path="/register" element={<Register />} />
            <Route path="/dashboard" element={<h1>工作台</h1>} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </RuntimeProfileContext.Provider>,
  )

const fillAndSubmit = async (user) => {
  await user.type(screen.getByLabelText('用户名'), 'alice')
  await user.type(screen.getByLabelText('邮箱'), 'alice@example.com')
  await user.type(screen.getByLabelText('密码'), 'Password1')
  await user.click(screen.getByRole('button', { name: /创建/ }))
}

describe('Register page errors', () => {
  let runtime

  beforeEach(() => {
    vi.mocked(api).mockReset()
    runtime = { profile: 'server', isLocal: false, requiresAuth: true, loading: false, markLocal: vi.fn() }
  })

  test('shows the readable server error instead of "Internal server error"', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(SERVER_ERROR_MESSAGE(500), { status: 500 }))
    const user = userEvent.setup()
    renderRegister(runtime)

    await fillAndSubmit(user)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('服务器出错了（500）')
    expect(alert.textContent).not.toMatch(/internal server error/i)
  })

  test('switches to local mode and opens the dashboard on the desktop 409', async () => {
    vi.mocked(api).mockRejectedValue(
      new ApiError('桌面版不需要注册或登录，直接使用即可', {
        status: 409,
        payload: { code: 'LocalProfileAuthUnavailable' },
      }),
    )
    const user = userEvent.setup()
    renderRegister(runtime)

    await fillAndSubmit(user)

    expect(await screen.findByRole('heading', { name: '工作台' })).toBeTruthy()
    expect(runtime.markLocal).toHaveBeenCalledTimes(1)
  })
})
