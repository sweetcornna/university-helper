import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { api } from '../utils/api'
import Zhihuishu from './Zhihuishu'

vi.mock('../utils/api', () => ({
  api: vi.fn(),
}))

vi.mock('../components', async (importOriginal) => {
  const toast = { notify: () => {} }
  return {
    ...(await importOriginal()),
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

const createApiMock = ({ tasks = [taskPayload], getTaskDetail = () => Promise.resolve({ data: taskPayload }) } = {}) => {
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
      return Promise.resolve({ data: tasks })
    }
    if (path.startsWith('/course/zhihuishu/tasks/')) {
      return getTaskDetail(path.split('/').pop())
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

    fireEvent.click(screen.getByRole('tab', { name: '课程' }))
    fireEvent.click(screen.getByRole('tab', { name: '任务' }))
    fireEvent.click(screen.getByRole('tab', { name: '账号' }))
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

  test('stops detail polling when the active task finishes', async () => {
    let task = taskPayload
    createApiMock({ getTaskDetail: async () => ({ data: task }) })
    renderPage()
    await flushPromises()
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(1)

    task = { ...taskPayload, status: 'completed' }
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000)
    })
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(2)
  })

  test('does not restart detail polling for a terminal task opened from the list', async () => {
    const finishedTask = { ...taskPayload, task_id: 'task-2', status: 'completed' }
    createApiMock({
      tasks: [taskPayload, finishedTask],
      getTaskDetail: async (taskId) => ({ data: taskId === 'task-2' ? finishedTask : taskPayload }),
    })
    renderPage()
    await flushPromises()
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(1)

    fireEvent.click(screen.getByRole('tab', { name: '任务' }))
    const details = (taskId) => {
      const row = screen.getByText(`任务 ID：${taskId}`, { exact: false, selector: 'li p' }).closest('li')
      return within(row).getByRole('button', { name: '查看详情' })
    }
    fireEvent.click(details('task-2'))
    await flushPromises()
    expect(countRequests('/course/zhihuishu/tasks/task-2')).toBe(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000)
    })
    expect(countRequests('/course/zhihuishu/tasks/task-2')).toBe(1)

    fireEvent.click(screen.getByRole('tab', { name: '学习配置' }))
    fireEvent.change(screen.getByLabelText('进度轮询间隔（秒）'), { target: { value: '2' } })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000)
    })
    expect(countRequests('/course/zhihuishu/tasks/task-2')).toBe(1)
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(1)

    fireEvent.click(screen.getByRole('tab', { name: '任务' }))
    fireEvent.click(details('task-2'))
    await flushPromises()
    expect(countRequests('/course/zhihuishu/tasks/task-2')).toBe(2)

    fireEvent.click(details('task-1'))
    await flushPromises()
    const requestsAfterSwitch = countRequests('/course/zhihuishu/tasks/task-1')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(requestsAfterSwitch + 1)
    expect(countRequests('/course/zhihuishu/tasks/task-2')).toBe(2)
  })
})
