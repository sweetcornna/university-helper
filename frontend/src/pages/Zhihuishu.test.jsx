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

const createApiMock = ({ taskDetail, verificationRefresh } = {}) => {
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
    if (path === '/course/zhihuishu/tasks/task-1/refresh-verification') {
      return verificationRefresh()
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
    act(() => { vi.runOnlyPendingTimers() })
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

  test('announces outstanding human verification without claiming that learning is complete', async () => {
    let requests = 0
    createApiMock({ taskDetail: () => {
      requests += 1
      return Promise.resolve({ data: requests === 1 ? taskPayload() : {
        ...taskPayload('completed'), completed: 1, percentage: 50, verification_required: 1,
      } })
    } })
    renderPage()
    await flushPromises()
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(screen.getByText(/自动处理结束，待人工验证 1 节/)).toBeInTheDocument()
    expect(screen.queryByText(/学习完成。/)).not.toBeInTheDocument()
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

describe('Zhihuishu speed setting', () => {
  beforeEach(() => {
    localStorage.clear()
    api.mockReset()
  })

  test('lists skipped verification lessons and removes them after a platform completion refresh', async () => {
    let manuallyCompleted = false
    const detail = () => ({
      ...taskPayload('completed'),
      completed: manuallyCompleted ? 2 : 1,
      percentage: manuallyCompleted ? 100 : 50,
      verification_required: manuallyCompleted ? 0 : 1,
      videos: [{ id: 'v1', title: '需人工处理的小节', status: manuallyCompleted ? 'completed' : 'needs_verification', error: '需要弹出滑块验证' }],
    })
    createApiMock({
      taskDetail: () => Promise.resolve({ data: detail() }),
      verificationRefresh: () => {
        manuallyCompleted = true
        return Promise.resolve({ data: detail() })
      },
    })
    renderPage()
    await flushPromises()
    fireEvent.click(screen.getByRole('tab', { name: '任务' }))
    expect(screen.getByText('待人工验证：1 节')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: '待人工验证小节' })).toHaveTextContent('需人工处理的小节')
    expect(screen.getByText('状态：自动处理结束，待人工处理')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '刷新人工处理结果' }))
    await flushPromises()
    expect(countRequests('/course/zhihuishu/tasks/task-1/refresh-verification')).toBe(1)
    expect(screen.queryByRole('list', { name: '待人工验证小节' })).not.toBeInTheDocument()
    expect(screen.getByText(/进度：2\/2/)).toBeInTheDocument()
  })

  test('preserves and displays the failed lesson reason from task details', async () => {
    createApiMock({ taskDetail: () => Promise.resolve({ data: {
      ...taskPayload('completed'),
      failed: 1,
      videos: [{ id: 'v1', title: '失败小节', status: 'failed', error: '提交学习进度：平台返回 code=-12，需要弹出滑块验证' }],
    } }) })
    renderPage()
    await flushPromises()
    fireEvent.click(screen.getByRole('tab', { name: '课程' }))
    expect(screen.getByText(/失败原因：提交学习进度：平台返回 code=-12，需要弹出滑块验证/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '任务' }))
    expect(screen.getByText(/请在智慧树官方播放器完成人工验证/)).toBeInTheDocument()
  })

  test('shows a whole-number speed from the config API as its option', async () => {
    // The config API answers speed: 1 (JSON drops the ".0"); the select's
    // options are "0.5", "1.0", ... so "1" used to fall back to showing 0.5x.
    createApiMock()
    renderPage()
    await flushPromises()

    fireEvent.click(screen.getByRole('tab', { name: '课程' }))

    const speed = screen.getByRole('combobox', { name: '学习倍速' })
    expect(speed).toHaveValue('1.0')
    expect(speed.selectedOptions[0]).toHaveTextContent('1.0x')
  })
})
