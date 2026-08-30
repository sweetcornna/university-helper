import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { ToastProvider } from '../components/Toast'
import { api } from '../utils/api'
import Zhihuishu from './Zhihuishu'

vi.mock('../utils/api', () => ({
  api: vi.fn(),
}))

const NEW_TASK_PATHS = {
  course: '/course/zhihuishu/tasks/course',
  'ai-course': '/course/zhihuishu/tasks/ai-course',
}
const LEGACY_TASK_PATH = '/course/zhihuishu/course/start'

const course = {
  courseId: 'course-1',
  name: '高等数学',
}

const taskResponse = (taskId = 'new-task') => ({
  task_id: taskId,
  task_type: 'course',
  course_id: course.courseId,
  course_name: course.name,
  status: 'running',
  message: '任务已启动。',
})

const postPaths = () => api.mock.calls
  .filter(([, options]) => options?.method === 'POST')
  .map(([path]) => path)

const renderPage = () => render(
  <ToastProvider>
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Zhihuishu />
    </MemoryRouter>
  </ToastProvider>,
)

const pendingRequest = () => new Promise(() => {})

const configureApi = ({ startBehavior, legacyResponse = taskResponse('legacy-task') } = {}) => {
  api.mockImplementation((path, options = {}) => {
    if (path === '/course/zhihuishu/status') {
      return Promise.resolve({ data: { logged_in: false } })
    }
    if (path === '/course/zhihuishu/config') {
      return Promise.resolve({ data: { speed: 1, auto_answer: true } })
    }
    if (path === '/course/zhihuishu/courses/grouped') {
      return Promise.resolve({ data: [{ group: '本学期', courses: [course] }] })
    }
    if (path === '/course/zhihuishu/courses/course-1') {
      return Promise.resolve({ data: course })
    }
    if (path.startsWith('/course/zhihuishu/tasks/') && options.method === 'GET') {
      return pendingRequest()
    }
    if (path === NEW_TASK_PATHS.course || path === NEW_TASK_PATHS['ai-course']) {
      return typeof startBehavior === 'function'
        ? startBehavior(path)
        : Promise.resolve(taskResponse())
    }
    if (path === LEGACY_TASK_PATH) {
      return Promise.resolve(legacyResponse)
    }
    return Promise.resolve({})
  })
}

const openCoursesAndSelectCourse = async () => {
  const coursesButton = await screen.findByRole('button', { name: '课程' })
  fireEvent.click(coursesButton)
  fireEvent.click(await screen.findByRole('button', { name: '刷新课程' }))
  const selector = await screen.findByRole('combobox', { name: '分组课程' })
  await waitFor(() => expect(selector).toHaveValue(course.courseId))
  return selector
}

const clickStart = async (taskType = 'course') => {
  await openCoursesAndSelectCourse()
  const name = taskType === 'ai-course' ? /启动 AI 任务/ : /启动课程任务/
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name }))
    await Promise.resolve()
  })
}

describe('Zhihuishu course-task startup fallback', () => {
  beforeEach(() => {
    localStorage.clear()
    api.mockReset()
  })

  afterEach(() => {
    vi.clearAllTimers()
  })

  test.each([
    ['404', 'course', 404],
    ['405', 'ai-course', 405],
  ])('falls back to legacy startup only for %s (%s path)', async (_label, taskType, status) => {
    configureApi({
      startBehavior: () => Promise.reject({ status, message: `new endpoint returned ${status}` }),
    })

    renderPage()
    await clickStart(taskType)

    await waitFor(() => expect(postPaths()).toEqual([
      NEW_TASK_PATHS[taskType],
      LEGACY_TASK_PATH,
    ]))
    if (taskType === 'course') {
      expect(await screen.findByText('任务 ID：legacy-task')).toBeInTheDocument()
    }
  })

  test('does not retry a new task POST after a 500 response', async () => {
    configureApi({
      startBehavior: () => Promise.reject({ status: 500, message: 'server failed after creating the task' }),
    })

    renderPage()
    await clickStart()

    await waitFor(() => expect(postPaths()).toEqual([NEW_TASK_PATHS.course]))
    expect(postPaths()).not.toContain(LEGACY_TASK_PATH)
  })

  test('does not retry a new task POST after a network rejection', async () => {
    configureApi({
      startBehavior: () => Promise.reject(new Error('network unavailable')),
    })

    renderPage()
    await clickStart()

    await waitFor(() => expect(postPaths()).toEqual([NEW_TASK_PATHS.course]))
    expect(postPaths()).not.toContain(LEGACY_TASK_PATH)
  })

  test('does not retry when the first POST may have created a task before its response was lost', async () => {
    let serverCreatedTask = false
    configureApi({
      startBehavior: () => {
        serverCreatedTask = true
        return Promise.reject(new Error('response lost after task creation'))
      },
    })

    renderPage()
    await clickStart()

    await waitFor(() => expect(postPaths()).toEqual([NEW_TASK_PATHS.course]))
    expect(serverCreatedTask).toBe(true)
    expect(postPaths()).not.toContain(LEGACY_TASK_PATH)
  })

  test('does not retry when the new endpoint returns an invalid success payload', async () => {
    configureApi({
      startBehavior: () => Promise.resolve({ message: 'accepted but no task id' }),
    })

    renderPage()
    await clickStart()

    await waitFor(() => expect(postPaths()).toEqual([NEW_TASK_PATHS.course]))
    expect(postPaths()).not.toContain(LEGACY_TASK_PATH)
  })

  test('uses a successful new endpoint response once without legacy startup', async () => {
    configureApi({ startBehavior: () => Promise.resolve(taskResponse('new-task')) })

    renderPage()
    await clickStart()

    await waitFor(() => expect(postPaths()).toEqual([NEW_TASK_PATHS.course]))
    expect(await screen.findByText('任务 ID：new-task')).toBeInTheDocument()
    expect(postPaths()).not.toContain(LEGACY_TASK_PATH)
  })
})
