import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

vi.mock('../../../components', () => ({
  useRuntimeProfile: () => ({ profile: 'local', isLocal: true, requiresAuth: false, loading: false }),
}))

vi.mock('../../../utils/api', () => ({
  api: vi.fn(),
}))

import { api } from '../../../utils/api'
import useAuthentication from './useAuthentication'

const stopPolling = vi.fn()

function AuthenticationHarness() {
  const auth = useAuthentication({ stopPolling })

  return (
    <>
      <input
        aria-label="账号"
        value={auth.username}
        onChange={(event) => auth.setUsername(event.target.value)}
      />
      <input
        aria-label="密码"
        value={auth.password}
        onChange={(event) => auth.setPassword(event.target.value)}
      />
      <button
        type="button"
        onClick={() => void auth.handleLogin({ preventDefault: () => {} })}
      >
        登录
      </button>
      <button
        type="button"
        onClick={() => {
          auth.setUsername('user-b')
          auth.setPassword('pass-b')
        }}
      >
        模拟修改凭据
      </button>
      <button type="button" onClick={() => void auth.loadCourses()}>
        刷新课程
      </button>
      <output data-testid="courses-loading">{String(auth.coursesLoading)}</output>
      <output data-testid="login-loading">{String(auth.loginLoading)}</output>
      <output data-testid="courses-error">{auth.error}</output>
      <output data-testid="courses-notice">{auth.notice}</output>
      <output data-testid="courses">{JSON.stringify(auth.courses)}</output>
    </>
  )
}

const renderAuthentication = () => render(
  <StrictMode>
    <MemoryRouter>
      <AuthenticationHarness />
    </MemoryRouter>
  </StrictMode>,
)

const deferred = () => {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('useAuthentication course refresh errors', () => {
  beforeEach(() => {
    api.mockReset()
    stopPolling.mockReset()
  })

  afterEach(() => {
    cleanup()
  })

  test.each([
    ['network rejection', new Error('网络连接失败')],
    ['HTTP 500', Object.assign(new Error('服务器错误（500）'), { status: 500 })],
  ])('shows a user-visible error for a %s without an unhandled rejection', async (_label, refreshError) => {
    api.mockRejectedValue(refreshError)
    const unhandledRejections = []
    const onUnhandledRejection = (event) => {
      event.preventDefault()
      unhandledRejections.push(event.reason)
    }
    window.addEventListener('unhandledrejection', onUnhandledRejection)

    try {
      const user = userEvent.setup()
      renderAuthentication()
      await user.click(screen.getByRole('button', { name: '刷新课程' }))

      await waitFor(() => expect(screen.getByTestId('courses-error')).toHaveTextContent(refreshError.message))
      await new Promise((resolve) => setTimeout(resolve, 0))
      expect(unhandledRejections).toHaveLength(0)
    } finally {
      window.removeEventListener('unhandledrejection', onUnhandledRejection)
    }
  })

  test('keeps the successful course and notice behavior', async () => {
    const courses = [{ courseId: 'course-1', name: '高等数学' }]
    api.mockResolvedValue({ courses })

    const user = userEvent.setup()
    renderAuthentication()
    await user.click(screen.getByRole('button', { name: '刷新课程' }))

    await waitFor(() => expect(screen.getByTestId('courses')).toHaveTextContent(JSON.stringify(courses)))
    expect(screen.getByTestId('courses-notice')).toHaveTextContent('已获取 1 门课程。')
    expect(screen.getByTestId('courses-error')).toBeEmptyDOMElement()
  })

  test('keeps the submitted credential snapshot through a successful course load', async () => {
    const login = deferred()
    const courses = deferred()
    api.mockImplementationOnce(() => login.promise).mockImplementationOnce(() => courses.promise)

    const user = userEvent.setup()
    renderAuthentication()
    await user.type(screen.getByRole('textbox', { name: '账号' }), 'user-a')
    await user.type(screen.getByRole('textbox', { name: '密码' }), 'pass-a')
    await user.click(screen.getByRole('button', { name: '登录' }))
    await waitFor(() => expect(screen.getByTestId('login-loading')).toHaveTextContent('true'))

    await user.click(screen.getByRole('button', { name: '模拟修改凭据' }))
    expect(screen.getByRole('textbox', { name: '账号' })).toHaveValue('user-b')
    expect(screen.getByRole('textbox', { name: '密码' })).toHaveValue('pass-b')

    await act(async () => {
      login.resolve({ status: true })
      await login.promise
    })
    await waitFor(() => expect(api).toHaveBeenCalledTimes(2))
    expect(JSON.parse(api.mock.calls[0][1].body)).toEqual({ username: 'user-a', password: 'pass-a' })

    await act(async () => {
      courses.resolve({ courses: [{ courseId: 'course-a', name: '课程 A' }] })
      await courses.promise
    })
    await waitFor(() => expect(screen.getByTestId('courses')).toHaveTextContent('course-a'))
    expect(screen.getByRole('textbox', { name: '账号' })).toHaveValue('user-a')
    expect(screen.getByRole('textbox', { name: '密码' })).toHaveValue('pass-a')
  })

  test('does not restore submitted credentials after a failed login', async () => {
    const login = deferred()
    api.mockImplementationOnce(() => login.promise)

    const user = userEvent.setup()
    renderAuthentication()
    await user.type(screen.getByRole('textbox', { name: '账号' }), 'user-a')
    await user.type(screen.getByRole('textbox', { name: '密码' }), 'pass-a')
    await user.click(screen.getByRole('button', { name: '登录' }))
    await waitFor(() => expect(screen.getByTestId('login-loading')).toHaveTextContent('true'))
    await user.click(screen.getByRole('button', { name: '模拟修改凭据' }))

    await act(async () => {
      login.reject(new Error('登录失败'))
      await login.promise.catch(() => undefined)
    })
    await waitFor(() => expect(screen.getByTestId('courses-error')).toHaveTextContent('登录失败'))
    expect(screen.getByRole('textbox', { name: '账号' })).toHaveValue('user-b')
    expect(screen.getByRole('textbox', { name: '密码' })).toHaveValue('pass-b')
  })

  test('clears a previous error and updates the notice after a later successful refresh', async () => {
    const courses = [{ courseId: 'course-2', name: '大学英语' }]
    api
      .mockRejectedValueOnce(new Error('第一次刷新失败'))
      .mockResolvedValueOnce({ courses })

    const user = userEvent.setup()
    renderAuthentication()
    const refreshButton = screen.getByRole('button', { name: '刷新课程' })

    await user.click(refreshButton)
    await waitFor(() => expect(screen.getByTestId('courses-error')).toHaveTextContent('第一次刷新失败'))

    await user.click(refreshButton)
    await waitFor(() => expect(screen.getByTestId('courses')).toHaveTextContent(JSON.stringify(courses)))
    expect(screen.getByTestId('courses-error')).toBeEmptyDOMElement()
    expect(screen.getByTestId('courses-notice')).toHaveTextContent('已获取 1 门课程。')
  })

  test('clears a previous notice when a later refresh fails', async () => {
    api
      .mockResolvedValueOnce({ courses: [{ courseId: 'course-3', name: '操作系统' }] })
      .mockRejectedValueOnce(new Error('第二次刷新失败'))

    const user = userEvent.setup()
    renderAuthentication()
    const refreshButton = screen.getByRole('button', { name: '刷新课程' })

    await user.click(refreshButton)
    await waitFor(() => expect(screen.getByTestId('courses-notice')).toHaveTextContent('已获取 1 门课程。'))

    await user.click(refreshButton)
    await waitFor(() => expect(screen.getByTestId('courses-error')).toHaveTextContent('第二次刷新失败'))
    expect(screen.getByTestId('courses-notice')).toBeEmptyDOMElement()
  })

  test('keeps the latest successful course refresh when responses resolve out of order', async () => {
    const first = deferred()
    const second = deferred()
    const coursesA = [{ courseId: 'course-a', name: '旧课程' }]
    const coursesB = [{ courseId: 'course-b', name: '新课程' }]
    api.mockImplementationOnce(() => first.promise).mockImplementationOnce(() => second.promise)

    const user = userEvent.setup()
    renderAuthentication()
    const refreshButton = screen.getByRole('button', { name: '刷新课程' })

    await user.click(refreshButton)
    await waitFor(() => expect(screen.getByTestId('courses-loading')).toHaveTextContent('true'))
    await user.click(refreshButton)

    await act(async () => {
      second.resolve({ courses: coursesB })
      await second.promise
    })
    await waitFor(() => expect(screen.getByTestId('courses')).toHaveTextContent(JSON.stringify(coursesB)))
    expect(screen.getByTestId('courses-loading')).toHaveTextContent('false')
    expect(screen.getByTestId('courses-notice')).toHaveTextContent('已获取 1 门课程。')

    await act(async () => {
      first.resolve({ courses: coursesA })
      await first.promise
    })
    expect(screen.getByTestId('courses')).toHaveTextContent(JSON.stringify(coursesB))
    expect(screen.getByTestId('courses-notice')).toHaveTextContent('已获取 1 门课程。')
    expect(screen.getByTestId('courses-error')).toBeEmptyDOMElement()
  })

  test('does not let an older refresh error overwrite a newer success', async () => {
    const first = deferred()
    const second = deferred()
    const coursesB = [{ courseId: 'course-b', name: '新课程' }]
    api.mockImplementationOnce(() => first.promise).mockImplementationOnce(() => second.promise)

    const user = userEvent.setup()
    renderAuthentication()
    const refreshButton = screen.getByRole('button', { name: '刷新课程' })

    await user.click(refreshButton)
    await user.click(refreshButton)

    await act(async () => {
      second.resolve({ courses: coursesB })
      await second.promise
      first.reject(new Error('旧刷新失败'))
      await first.promise.catch(() => undefined)
    })
    await waitFor(() => expect(screen.getByTestId('courses')).toHaveTextContent(JSON.stringify(coursesB)))
    expect(screen.getByTestId('courses-error')).toBeEmptyDOMElement()
    expect(screen.getByTestId('courses-loading')).toHaveTextContent('false')
  })

  test('shares latest-wins ownership between login loading and manual refresh', async () => {
    const login = Promise.resolve({ status: true })
    const loginCourses = deferred()
    const manualRefresh = deferred()
    const coursesB = [{ courseId: 'course-b', name: '新课程' }]
    api
      .mockImplementationOnce(() => login)
      .mockImplementationOnce(() => loginCourses.promise)
      .mockImplementationOnce(() => manualRefresh.promise)

    const user = userEvent.setup()
    renderAuthentication()
    await user.type(screen.getByRole('textbox', { name: '账号' }), 'user')
    await user.type(screen.getByRole('textbox', { name: '密码' }), 'pass')
    await user.click(screen.getByRole('button', { name: '登录' }))
    await waitFor(() => expect(screen.getByTestId('courses-loading')).toHaveTextContent('true'))

    await user.click(screen.getByRole('button', { name: '刷新课程' }))
    await act(async () => {
      manualRefresh.resolve({ courses: coursesB })
      await manualRefresh.promise
    })
    await waitFor(() => expect(screen.getByTestId('courses')).toHaveTextContent(JSON.stringify(coursesB)))
    expect(screen.getByTestId('courses-loading')).toHaveTextContent('false')

    await act(async () => {
      loginCourses.reject(new Error('旧登录课程加载失败'))
      await loginCourses.promise.catch(() => undefined)
    })
    expect(screen.getByTestId('courses')).toHaveTextContent(JSON.stringify(coursesB))
    expect(screen.getByTestId('courses-error')).toBeEmptyDOMElement()
    expect(screen.getByTestId('login-loading')).toHaveTextContent('false')
  })

  test('does not render again when a pending course load settles after unmount', async () => {
    const pending = deferred()
    api.mockImplementationOnce(() => pending.promise)
    let renderCount = 0
    const HarnessWithRenderCount = () => {
      renderCount += 1
      return <AuthenticationHarness />
    }

    const user = userEvent.setup()
    const rendered = render(
      <StrictMode>
        <MemoryRouter>
          <HarnessWithRenderCount />
        </MemoryRouter>
      </StrictMode>,
    )
    await user.click(screen.getByRole('button', { name: '刷新课程' }))
    const renderCountAtUnmount = renderCount
    rendered.unmount()

    await act(async () => {
      pending.resolve({ courses: [{ courseId: 'late' }] })
      await pending.promise
    })
    expect(renderCount).toBe(renderCountAtUnmount)
  })
})
