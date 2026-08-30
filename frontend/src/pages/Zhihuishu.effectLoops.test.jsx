import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { api } from '../utils/api'
import Zhihuishu from './Zhihuishu'

vi.mock('../utils/api', () => ({
  api: vi.fn(),
}))

vi.mock('../components', () => {
  const toast = { notify: () => {} }
  return {
    Input: ({ label, ...props }) => (
      <label>
        {label}
        <input {...props} />
      </label>
    ),
    Toggle: ({ checked, onChange, label, disabled = false, id }) => (
      <button
        type="button"
        role="switch"
        id={id}
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => !disabled && onChange(!checked)}
      />
    ),
    useRuntimeProfile: () => ({
      profile: 'local',
      isLocal: true,
      requiresAuth: false,
      loading: false,
    }),
    useToast: () => toast,
  }
})

const taskPayload = {
  task_id: 'task-1',
  task_type: 'course',
  course_id: 'course-1',
  course_name: '高等数学',
  status: 'running',
  message: 'Task is running',
  total: 2,
  completed: 1,
  failed: 0,
  percentage: 50,
}

const countRequests = (path) =>
  api.mock.calls.filter(([requestPath]) => requestPath === path).length

const createApiMock = () => {
  api.mockImplementation((path) => {
    if (path === '/course/zhihuishu/config') {
      return Promise.resolve({ data: { speed: 1, auto_answer: true } })
    }
    if (path === '/course/zhihuishu/status') {
      return Promise.resolve({ data: { logged_in: true } })
    }
    if (path === '/course/zhihuishu/courses/grouped') {
      return Promise.resolve({
        data: [{ group: '本学期', courses: [{ courseId: 'course-1', name: '高等数学' }] }],
      })
    }
    if (path === '/course/zhihuishu/tasks') {
      return Promise.resolve({ data: [taskPayload] })
    }
    if (path === '/course/zhihuishu/tasks/task-1') {
      return Promise.resolve({ data: taskPayload })
    }
    if (path === '/course/zhihuishu/courses/course-1') {
      return Promise.resolve({ data: { courseId: 'course-1', name: '高等数学' } })
    }
    throw new Error(`Unexpected API request: ${path}`)
  })
}

const renderPage = () => render(
  <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    <Zhihuishu />
  </MemoryRouter>,
)

const flushPromises = async () => {
  await act(async () => {
    for (let index = 0; index < 12; index += 1) {
      await Promise.resolve()
    }
  })
}

describe('Zhihuishu effect feedback loops', () => {
  beforeEach(() => {
    localStorage.clear()
    api.mockReset()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.runOnlyPendingTimers()
    vi.useRealTimers()
  })

  test('keeps logged-in bootstrap requests bounded across state refreshes', async () => {
    createApiMock()
    renderPage()
    await flushPromises()

    fireEvent.click(screen.getByText('课程'))
    fireEvent.click(screen.getByText('任务'))
    fireEvent.click(screen.getByText('登录'))
    await flushPromises()

    expect(countRequests('/course/zhihuishu/status')).toBe(1)
    expect(countRequests('/course/zhihuishu/config')).toBe(1)
    expect(countRequests('/course/zhihuishu/courses/grouped')).toBe(1)
    expect(countRequests('/course/zhihuishu/tasks')).toBe(1)
  })

  test('waits for the polling interval after a detail response updates state', async () => {
    createApiMock()
    renderPage()
    await flushPromises()

    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4999)
    })
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(2)
  })
})
