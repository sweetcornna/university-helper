import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
      <button type="button" onClick={() => void auth.loadCourses()}>
        刷新课程
      </button>
      <output data-testid="courses-error">{auth.error}</output>
      <output data-testid="courses-notice">{auth.notice}</output>
      <output data-testid="courses">{JSON.stringify(auth.courses)}</output>
    </>
  )
}

const renderAuthentication = () => render(
  <MemoryRouter>
    <AuthenticationHarness />
  </MemoryRouter>,
)

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
})
