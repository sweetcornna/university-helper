import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { RuntimeProfileContext } from '../components/runtimeProfileContext'
import { ToastProvider } from '../components/Toast'
import { api } from '../utils/api'
import Zhihuishu from './Zhihuishu'

vi.mock('../utils/api', () => ({
  api: vi.fn(),
}))

const runtimeProfile = {
  profile: 'local',
  isLocal: true,
  requiresAuth: false,
  loading: false,
}

const countRequests = (path) =>
  api.mock.calls.filter(([requestPath]) => requestPath === path).length

const taskPayload = (status = 'running') => ({
  task_id: 'task-1',
  task_type: 'course',
  course_id: 'course-1',
  course_name: '高等数学',
  status,
  message: status === 'completed' ? 'Task completed' : 'Task is running',
  total: 2,
  completed: status === 'completed' ? 2 : 1,
  failed: 0,
  percentage: status === 'completed' ? 100 : 50,
})

const createApiMock = ({ taskDetail } = {}) => {
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
      return Promise.resolve({ data: [taskPayload()] })
    }
    if (path === '/course/zhihuishu/tasks/task-1') {
      return taskDetail ? taskDetail() : Promise.resolve({ data: taskPayload() })
    }
    if (path === '/course/zhihuishu/tasks/task-1/cancel') {
      return Promise.resolve({ message: '任务已取消。' })
    }
    if (path === '/course/zhihuishu/courses/course-1') {
      return Promise.resolve({ data: { courseId: 'course-1', name: '高等数学' } })
    }
    throw new Error(`Unexpected API request: ${path}`)
  })
}

const renderPage = () => render(
  <RuntimeProfileContext.Provider value={runtimeProfile}>
    <ToastProvider>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Zhihuishu />
      </MemoryRouter>
    </ToastProvider>
  </RuntimeProfileContext.Provider>,
)

const flushPromises = async () => {
  await act(async () => {
    for (let index = 0; index < 12; index += 1) {
      await Promise.resolve()
    }
  })
}

describe('Zhihuishu task polling', () => {
  beforeEach(() => {
    localStorage.clear()
    api.mockReset()
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.runOnlyPendingTimers()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  test('bootstraps once and polls at the configured interval', async () => {
    createApiMock()
    renderPage()
    await flushPromises()

    expect(countRequests('/course/zhihuishu/status')).toBe(1)
    expect(countRequests('/course/zhihuishu/courses/grouped')).toBe(1)
    expect(countRequests('/course/zhihuishu/tasks')).toBe(1)
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4999)
    })
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(2)
    expect(countRequests('/course/zhihuishu/tasks')).toBe(1)
  })

  test('does not overlap requests for the same task', async () => {
    let resolveTaskDetail
    const pendingTaskDetail = new Promise((resolve) => {
      resolveTaskDetail = resolve
    })
    createApiMock({ taskDetail: () => pendingTaskDetail })

    renderPage()
    await flushPromises()
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000)
    })
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(1)

    await act(async () => {
      resolveTaskDetail({ data: taskPayload() })
      await pendingTaskDetail
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(2)
  })

  test('stops polling when a task reaches a terminal state', async () => {
    let detailRequests = 0
    createApiMock({
      taskDetail: () => {
        detailRequests += 1
        return Promise.resolve({
          data: taskPayload(detailRequests === 1 ? 'running' : 'completed'),
        })
      },
    })

    renderPage()
    await flushPromises()
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(2)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000)
    })
    expect(countRequests('/course/zhihuishu/tasks/task-1')).toBe(2)
  })

  test('does not cancel an individual task when confirmation is rejected', async () => {
    window.confirm.mockReturnValue(false)
    createApiMock()
    renderPage()
    await flushPromises()

    fireEvent.click(screen.getByRole('tab', { name: '任务' }))
    fireEvent.click(screen.getByRole('button', { name: '取消该任务' }))
    await flushPromises()

    expect(window.confirm).toHaveBeenCalledWith('确定要取消该任务吗？此操作不可撤销。')
    expect(countRequests('/course/zhihuishu/tasks/task-1/cancel')).toBe(0)
  })
})
