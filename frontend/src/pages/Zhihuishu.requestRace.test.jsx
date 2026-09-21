import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { api } from '../utils/api'
import Zhihuishu from './Zhihuishu'

const toast = vi.hoisted(() => ({ notify: vi.fn() }))

vi.mock('../utils/api', () => ({
  api: vi.fn(),
}))

vi.mock('../components', () => ({
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
}))

const API_BASE = '/course/zhihuishu'
const COURSE_A = 'course-a'
const COURSE_B = 'course-b'

const deferred = () => {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

const courseGroupsResponse = {
  data: [{
    group: '本学期',
    courses: [
      { courseId: COURSE_A, name: '课程 A' },
      { courseId: COURSE_B, name: '课程 B' },
    ],
  }],
}

const courseDetailResponse = (courseId, name, videoName) => ({
  data: {
    courseId,
    name,
    chapters: videoName
      ? [{
          chapterId: `${courseId}-chapter`,
          chapterName: `${name} 章节`,
          videos: [{ id: `${courseId}-video`, title: videoName }],
        }]
      : [],
  },
})

const taskResponse = (taskId, courseId = COURSE_A, status = 'running', videos = []) => ({
  task_id: taskId,
  task_type: 'course',
  course_id: courseId,
  course_name: courseId === COURSE_A ? '课程 A' : '课程 B',
  status,
  message: status === 'completed' ? `${taskId} 完成` : `${taskId} 运行中`,
  total: 2,
  completed: status === 'completed' ? 2 : 1,
  failed: 0,
  percentage: status === 'completed' ? 100 : 50,
  videos,
})

const countRequests = (path) => api.mock.calls.filter(([requestPath]) => requestPath === path).length

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

const settle = async (request, value) => {
  await act(async () => {
    request.resolve(value)
    await Promise.resolve()
  })
  await flushPromises()
}

const fail = async (request, error) => {
  await act(async () => {
    request.reject(error)
    await Promise.resolve()
  })
  await flushPromises()
}

const getWorkspaceTab = (name) => {
  const accessibleName = name === 'status' ? /^状态(?:\/|与)退出$/ : name
  return screen.queryByRole('tab', { name: accessibleName })
    || screen.getByRole('button', { name: accessibleName })
}

const getZhihuishuLogoutButton = () => screen.getByRole('button', {
  name: /^退出智慧树会话(?:（后端）)?$/,
})

const configureCourseApi = ({ courseDetails = {}, progress = {}, videos = {} } = {}) => {
  api.mockImplementation((path) => {
    if (path === `${API_BASE}/config`) return Promise.resolve({ data: {} })
    if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
    if (path === `${API_BASE}/courses/grouped`) return Promise.resolve(courseGroupsResponse)
    if (path.startsWith(`${API_BASE}/courses/`)) {
      const courseId = path.split('/').pop()
      return typeof courseDetails[courseId] === 'function'
        ? courseDetails[courseId]()
        : Promise.resolve(courseDetails[courseId] || courseDetailResponse(courseId, courseId))
    }
    if (path.startsWith(`${API_BASE}/progress/`)) {
      const courseId = path.split('/').pop()
      return typeof progress[courseId] === 'function'
        ? progress[courseId]()
        : Promise.resolve(progress[courseId] || { data: { status: 'running' } })
    }
    if (path.startsWith(`${API_BASE}/videos/`)) {
      const courseId = path.split('/').pop()
      return typeof videos[courseId] === 'function'
        ? videos[courseId]()
        : Promise.resolve(videos[courseId] || { data: [] })
    }
    throw new Error(`Unexpected API request: ${path}`)
  })
}

const openCourses = async () => {
  renderPage()
  await flushPromises()
  fireEvent.click(getWorkspaceTab('课程'))
  fireEvent.click(await screen.findByRole('button', { name: '刷新课程' }))
  const selector = await screen.findByRole('combobox', { name: '分组课程' })
  await waitFor(() => expect(selector).toHaveValue(COURSE_A))
  return selector
}

const openTasksAndRefresh = async () => {
  fireEvent.click(getWorkspaceTab('任务'))
  fireEvent.click(await screen.findByRole('button', { name: '刷新列表' }))
  await screen.findByText('任务 ID：task-a')
}

const changePollInterval = async (seconds) => {
  fireEvent.click(getWorkspaceTab('设置'))
  fireEvent.change(screen.getByLabelText('进度轮询间隔（秒）'), {
    target: { value: String(seconds) },
  })
  await flushPromises()
}

const advanceTimers = async (milliseconds) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds)
  })
  await flushPromises()
}

const qrLoginResponse = (sessionId, qrCode, message = '请使用智慧树 App 扫码。') => ({
  session_id: sessionId,
  qr_code: qrCode,
  status: 'pending',
  message,
})

describe('Zhihuishu request race guards', () => {
  beforeEach(() => {
    localStorage.clear()
    api.mockReset()
    toast.notify.mockReset()
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  test('ignores an older course detail response after switching courses', async () => {
    const courseARequest = deferred()
    const courseBRequest = deferred()
    configureCourseApi({
      courseDetails: {
        [COURSE_A]: () => courseARequest.promise,
        [COURSE_B]: () => courseBRequest.promise,
      },
    })

    const selector = await openCourses()
    await waitFor(() => expect(countRequests(`${API_BASE}/courses/${COURSE_A}`)).toBe(1))

    fireEvent.change(selector, { target: { value: COURSE_B } })
    await waitFor(() => expect(countRequests(`${API_BASE}/courses/${COURSE_B}`)).toBe(1))

    await settle(courseARequest, courseDetailResponse(COURSE_A, '课程 A', 'A 视频'))
    expect(screen.queryByText('课程 A 章节')).not.toBeInTheDocument()
    expect(screen.getByText('正在加载课程详情...')).toBeInTheDocument()

    await settle(courseBRequest, courseDetailResponse(COURSE_B, '课程 B', 'B 视频'))
    expect(screen.getByText('课程 B 章节')).toBeInTheDocument()
    expect(screen.queryByText('课程 A 章节')).not.toBeInTheDocument()
  })

  test('clears the previous course view before a pending switch and on deselect', async () => {
    const courseBRequest = deferred()
    configureCourseApi({
      courseDetails: {
        [COURSE_A]: () => Promise.resolve(courseDetailResponse(COURSE_A, '课程 A', 'A 课程视频')),
        [COURSE_B]: () => courseBRequest.promise,
      },
      progress: {
        [COURSE_A]: () => Promise.resolve({
          data: {
            status: 'running',
            message: 'A 课程进度',
            total: 2,
            completed: 1,
            percentage: 50,
          },
        }),
      },
    })

    const selector = await openCourses()
    await waitFor(() => expect(screen.getByText('课程 A 章节')).toBeInTheDocument())
    expect(screen.getByText('A 课程视频')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '刷新进度' }))
    await waitFor(() => expect(screen.getByText('消息：A 课程进度')).toBeInTheDocument())

    fireEvent.change(selector, { target: { value: COURSE_B } })
    await waitFor(() => expect(countRequests(`${API_BASE}/courses/${COURSE_B}`)).toBe(1))
    expect(screen.queryByText('课程 A 章节')).not.toBeInTheDocument()
    expect(screen.queryByText('A 课程视频')).not.toBeInTheDocument()
    expect(screen.queryByText('消息：A 课程进度')).not.toBeInTheDocument()
    expect(screen.getByText('正在加载课程详情...')).toBeInTheDocument()

    await settle(courseBRequest, courseDetailResponse(COURSE_B, '课程 B', 'B 课程视频'))
    expect(screen.getByText('课程 B 章节')).toBeInTheDocument()
    expect(screen.getByText('B 课程视频')).toBeInTheDocument()
    expect(screen.queryByText('课程 A 章节')).not.toBeInTheDocument()
    expect(screen.queryByText('A 课程视频')).not.toBeInTheDocument()

    fireEvent.change(selector, { target: { value: '' } })
    expect(screen.getByText('请选择课程查看详情与进度。')).toBeInTheDocument()
    expect(screen.queryByText('消息：A 课程进度')).not.toBeInTheDocument()
  })

  test('invalidates A synchronously when a refreshed course list automatically selects B', async () => {
    const courseARequest = deferred()
    const courseBRequest = deferred()
    let groupedCalls = 0
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/config`) return Promise.resolve({ data: {} })
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
      if (path === `${API_BASE}/courses/grouped`) {
        groupedCalls += 1
        return Promise.resolve(groupedCalls === 1
          ? courseGroupsResponse
          : { data: [{ group: '本学期', courses: [{ courseId: COURSE_B, name: '课程 B' }] }] })
      }
      if (path === `${API_BASE}/courses/${COURSE_A}`) return courseARequest.promise
      if (path === `${API_BASE}/courses/${COURSE_B}`) return courseBRequest.promise
      throw new Error(`Unexpected API request: ${path}`)
    })

    const selector = await openCourses()
    await waitFor(() => expect(countRequests(`${API_BASE}/courses/${COURSE_A}`)).toBe(1))

    fireEvent.click(screen.getByRole('button', { name: '刷新课程' }))
    await waitFor(() => expect(selector).toHaveValue(COURSE_B))
    await waitFor(() => expect(countRequests(`${API_BASE}/courses/${COURSE_B}`)).toBe(1))

    await settle(courseARequest, courseDetailResponse(COURSE_A, '课程 A', 'A 旧视频'))
    expect(screen.queryByText('课程 A 章节')).not.toBeInTheDocument()
    expect(screen.getByText('正在加载课程详情...')).toBeInTheDocument()

    await settle(courseBRequest, courseDetailResponse(COURSE_B, '课程 B', 'B 新视频'))
    expect(screen.getByText('课程 B 章节')).toBeInTheDocument()
    expect(screen.queryByText('课程 A 章节')).not.toBeInTheDocument()
  })

  test('old progress and video successes neither overwrite B nor clear B loading', async () => {
    const progressARequest = deferred()
    const progressBRequest = deferred()
    const videosARequest = deferred()
    const videosBRequest = deferred()
    configureCourseApi({
      progress: {
        [COURSE_A]: () => progressARequest.promise,
        [COURSE_B]: () => progressBRequest.promise,
      },
      videos: {
        [COURSE_A]: () => videosARequest.promise,
        [COURSE_B]: () => videosBRequest.promise,
      },
    })

    const selector = await openCourses()
    fireEvent.click(screen.getByRole('button', { name: '刷新进度' }))
    fireEvent.click(screen.getByRole('button', { name: '查看视频列表/结构' }))
    await waitFor(() => expect(countRequests(`${API_BASE}/videos/${COURSE_A}`)).toBe(1))

    fireEvent.change(selector, { target: { value: COURSE_B } })
    fireEvent.click(screen.getByRole('button', { name: '刷新进度' }))
    fireEvent.click(screen.getByRole('button', { name: '查看视频列表/结构' }))
    await waitFor(() => expect(countRequests(`${API_BASE}/videos/${COURSE_B}`)).toBe(1))

    await settle(progressARequest, { data: { status: 'running', message: 'A 旧进度' } })
    await settle(videosARequest, { data: [{ id: 'a-video', name: 'A 旧视频' }] })
    expect(screen.queryByText('A 旧视频')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新中...' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '加载中...' })).toBeInTheDocument()

    await settle(progressBRequest, { data: { status: 'running', message: 'B 新进度' } })
    await settle(videosBRequest, { data: [{ id: 'b-video', name: 'B 新视频' }] })
    expect(screen.getByText('消息：B 新进度')).toBeInTheDocument()
    expect(screen.getByText('B 新视频')).toBeInTheDocument()
  })

  test('old progress and video errors neither notify nor clear B loading', async () => {
    const progressARequest = deferred()
    const progressBRequest = deferred()
    const videosARequest = deferred()
    const videosBRequest = deferred()
    configureCourseApi({
      progress: {
        [COURSE_A]: () => progressARequest.promise,
        [COURSE_B]: () => progressBRequest.promise,
      },
      videos: {
        [COURSE_A]: () => videosARequest.promise,
        [COURSE_B]: () => videosBRequest.promise,
      },
    })

    const selector = await openCourses()
    fireEvent.click(screen.getByRole('button', { name: '刷新进度' }))
    fireEvent.click(screen.getByRole('button', { name: '查看视频列表/结构' }))
    await waitFor(() => expect(countRequests(`${API_BASE}/videos/${COURSE_A}`)).toBe(1))

    fireEvent.change(selector, { target: { value: COURSE_B } })
    fireEvent.click(screen.getByRole('button', { name: '刷新进度' }))
    fireEvent.click(screen.getByRole('button', { name: '查看视频列表/结构' }))
    await waitFor(() => expect(countRequests(`${API_BASE}/videos/${COURSE_B}`)).toBe(1))

    toast.notify.mockReset()
    await fail(progressARequest, new Error('A 旧进度失败'))
    await fail(videosARequest, new Error('A 旧视频失败'))
    expect(toast.notify).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '刷新中...' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '加载中...' })).toBeInTheDocument()

    await settle(progressBRequest, { data: { status: 'running', message: 'B 仍有效' } })
    await settle(videosBRequest, { data: [{ id: 'b-video', name: 'B 视频仍有效' }] })
    expect(screen.getByText('消息：B 仍有效')).toBeInTheDocument()
    expect(screen.getByText('B 视频仍有效')).toBeInTheDocument()
  })

  test('does not write course, progress, video, or task state after unmount', async () => {
    const firstCourseRequest = deferred()
    const videoCourseRequest = deferred()
    const progressRequest = deferred()
    const taskRequest = deferred()
    let courseCalls = 0
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/config`) return Promise.resolve({ data: {} })
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
      if (path === `${API_BASE}/courses/grouped`) return Promise.resolve(courseGroupsResponse)
      if (path === `${API_BASE}/courses/${COURSE_A}`) {
        courseCalls += 1
        return courseCalls === 1 ? firstCourseRequest.promise : videoCourseRequest.promise
      }
      if (path === `${API_BASE}/progress/${COURSE_A}`) return progressRequest.promise
      if (path === `${API_BASE}/tasks`) return Promise.resolve({ data: [taskResponse('task-a')] })
      if (path === `${API_BASE}/tasks/task-a`) return taskRequest.promise
      throw new Error(`Unexpected API request: ${path}`)
    })

    const page = renderPage()
    await flushPromises()
    fireEvent.click(getWorkspaceTab('课程'))
    fireEvent.click(screen.getByRole('button', { name: '刷新课程' }))
    await waitFor(() => expect(screen.getByRole('combobox', { name: '分组课程' })).toHaveValue(COURSE_A))
    await openTasksAndRefresh()
    await waitFor(() => expect(countRequests(`${API_BASE}/tasks/task-a`)).toBe(1))
    fireEvent.click(getWorkspaceTab('课程'))
    fireEvent.click(screen.getByRole('button', { name: '刷新进度' }))
    fireEvent.click(screen.getByRole('button', { name: '查看视频列表/结构' }))

    toast.notify.mockReset()
    page.unmount()
    await settle(firstCourseRequest, courseDetailResponse(COURSE_A, '课程 A'))
    await settle(videoCourseRequest, courseDetailResponse(COURSE_A, '课程 A', 'A 视频'))
    await settle(progressRequest, { data: { status: 'completed', message: '卸载后进度' } })
    await settle(taskRequest, { data: taskResponse('task-a', COURSE_A, 'completed') })
    expect(toast.notify).not.toHaveBeenCalled()
  })

  test('reset immediately clears the session and invalidates an in-flight task response', async () => {
    const taskRequest = deferred()
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/config`) return Promise.resolve({ data: {} })
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
      if (path === `${API_BASE}/courses/grouped`) return Promise.resolve(courseGroupsResponse)
      if (path.startsWith(`${API_BASE}/courses/`)) return Promise.resolve(courseDetailResponse(COURSE_A, '课程 A'))
      if (path === `${API_BASE}/tasks`) return Promise.resolve({ data: [taskResponse('task-a')] })
      if (path === `${API_BASE}/tasks/task-a`) return taskRequest.promise
      if (path === `${API_BASE}/logout`) return Promise.resolve({ message: '已退出' })
      throw new Error(`Unexpected API request: ${path}`)
    })

    await openCourses()
    await openTasksAndRefresh()
    await waitFor(() => expect(countRequests(`${API_BASE}/tasks/task-a`)).toBe(1))

    fireEvent.click(getWorkspaceTab('status'))
    fireEvent.click(screen.getByRole('button', { name: '清理智慧树会话状态' }))
    await flushPromises()
    expect(screen.getByText('任务总数：0')).toBeInTheDocument()
    toast.notify.mockReset()

    await settle(taskRequest, { data: taskResponse('task-a', COURSE_A, 'completed') })
    expect(screen.getByText('任务总数：0')).toBeInTheDocument()
    expect(toast.notify.mock.calls.some(([, message]) => String(message).includes('学习完成'))).toBe(false)
    fireEvent.click(getWorkspaceTab('任务'))
    expect(screen.queryByText('任务 ID：task-a')).not.toBeInTheDocument()
  })

  test('failed logout preserves the session, blocks old task writes, and allows a new poll', async () => {
    const oldTaskRequest = deferred()
    const newTaskRequest = deferred()
    const logoutRequest = deferred()
    let taskCalls = 0
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/config`) return Promise.resolve({ data: {} })
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: true } })
      if (path === `${API_BASE}/courses/grouped`) return Promise.resolve(courseGroupsResponse)
      if (path.startsWith(`${API_BASE}/courses/`)) return Promise.resolve(courseDetailResponse(COURSE_A, '课程 A'))
      if (path === `${API_BASE}/tasks`) return Promise.resolve({ data: [taskResponse('task-a')] })
      if (path === `${API_BASE}/tasks/task-a`) {
        taskCalls += 1
        return taskCalls === 1 ? oldTaskRequest.promise : newTaskRequest.promise
      }
      if (path === `${API_BASE}/logout`) return logoutRequest.promise
      throw new Error(`Unexpected API request: ${path}`)
    })

    renderPage()
    await flushPromises()
    await waitFor(() => expect(taskCalls).toBe(1))
    fireEvent.click(getWorkspaceTab('status'))
    expect(screen.getByText('智慧树登录：已登录')).toBeInTheDocument()
    expect(screen.getByText('活跃任务 ID：task-a')).toBeInTheDocument()
    expect(screen.getByText('任务总数：1')).toBeInTheDocument()

    fireEvent.click(getZhihuishuLogoutButton())
    await settle(oldTaskRequest, { data: taskResponse('task-a', COURSE_A, 'completed') })
    await fail(logoutRequest, new Error('退出保留失败'))

    expect(screen.getByText('智慧树登录：已登录')).toBeInTheDocument()
    expect(screen.getByText('活跃任务 ID：task-a')).toBeInTheDocument()
    expect(screen.getByText('任务总数：1')).toBeInTheDocument()
    expect(screen.getByText('状态：running')).toBeInTheDocument()
    expect(toast.notify).toHaveBeenCalledWith('error', '退出保留失败')
    expect(toast.notify.mock.calls.some(([, message]) => String(message).includes('学习完成'))).toBe(false)
    fireEvent.click(getWorkspaceTab('课程'))
    expect(screen.getByRole('combobox', { name: '分组课程' })).toHaveValue(COURSE_A)

    await changePollInterval(2)
    await waitFor(() => expect(taskCalls).toBe(2))
    await settle(newTaskRequest, { data: taskResponse('task-a', COURSE_A, 'completed') })
    fireEvent.click(getWorkspaceTab('status'))
    expect(screen.getByText('状态：completed')).toBeInTheDocument()
  })

  test('successful logout clears the session and blocks its old in-flight task response', async () => {
    const taskRequest = deferred()
    const logoutRequest = deferred()
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/config`) return Promise.resolve({ data: {} })
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: true } })
      if (path === `${API_BASE}/courses/grouped`) return Promise.resolve(courseGroupsResponse)
      if (path.startsWith(`${API_BASE}/courses/`)) return Promise.resolve(courseDetailResponse(COURSE_A, '课程 A'))
      if (path === `${API_BASE}/tasks`) return Promise.resolve({ data: [taskResponse('task-a')] })
      if (path === `${API_BASE}/tasks/task-a`) return taskRequest.promise
      if (path === `${API_BASE}/logout`) return logoutRequest.promise
      throw new Error(`Unexpected API request: ${path}`)
    })

    renderPage()
    await flushPromises()
    await waitFor(() => expect(countRequests(`${API_BASE}/tasks/task-a`)).toBe(1))
    fireEvent.click(getWorkspaceTab('status'))
    fireEvent.click(getZhihuishuLogoutButton())
    await flushPromises()
    expect(screen.getByText('智慧树登录：已登录')).toBeInTheDocument()
    expect(screen.getByText('任务总数：1')).toBeInTheDocument()

    await settle(logoutRequest, { message: '已退出' })
    expect(screen.getByText('智慧树登录：未登录')).toBeInTheDocument()
    expect(screen.getByText('活跃任务 ID：无')).toBeInTheDocument()
    expect(screen.getByText('任务总数：0')).toBeInTheDocument()
    toast.notify.mockReset()

    await settle(taskRequest, { data: taskResponse('task-a', COURSE_A, 'completed') })
    expect(screen.getByText('任务总数：0')).toBeInTheDocument()
    expect(toast.notify.mock.calls.some(([, message]) => String(message).includes('学习完成'))).toBe(false)
    fireEvent.click(getWorkspaceTab('任务'))
    expect(screen.queryByText('任务 ID：task-a')).not.toBeInTheDocument()
  })

  test('a newer request for the same task wins over the older response', async () => {
    const olderRequest = deferred()
    const newerRequest = deferred()
    let taskCalls = 0
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/config`) return Promise.resolve({ data: {} })
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
      if (path === `${API_BASE}/courses/grouped`) return Promise.resolve(courseGroupsResponse)
      if (path.startsWith(`${API_BASE}/courses/`)) return Promise.resolve(courseDetailResponse(COURSE_A, '课程 A'))
      if (path === `${API_BASE}/tasks`) return Promise.resolve({ data: [taskResponse('task-a')] })
      if (path === `${API_BASE}/tasks/task-a`) {
        taskCalls += 1
        if (taskCalls === 1) return Promise.resolve({ data: taskResponse('task-a') })
        return taskCalls === 2 ? olderRequest.promise : newerRequest.promise
      }
      throw new Error(`Unexpected API request: ${path}`)
    })

    await openCourses()
    await openTasksAndRefresh()
    await waitFor(() => expect(countRequests(`${API_BASE}/tasks/task-a`)).toBe(1))
    const detailButton = screen.getByRole('button', { name: '查看详情' })
    fireEvent.click(detailButton)
    fireEvent.click(detailButton)
    await waitFor(() => expect(countRequests(`${API_BASE}/tasks/task-a`)).toBe(3))

    await settle(newerRequest, { data: taskResponse('task-a', COURSE_A, 'completed') })
    await settle(olderRequest, { data: taskResponse('task-a', COURSE_A, 'running') })
    expect(screen.getByText('状态：completed')).toBeInTheDocument()
    expect(screen.queryByText('task-a 运行中')).not.toBeInTheDocument()
  })

  test('a later silent A poll cannot invalidate the pending manual B request', async () => {
    const manualBRequest = deferred()
    const laterSilentARequest = deferred()
    let taskACalls = 0
    let taskBCalls = 0
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/config`) return Promise.resolve({ data: {} })
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
      if (path === `${API_BASE}/courses/grouped`) return Promise.resolve(courseGroupsResponse)
      if (path.startsWith(`${API_BASE}/courses/`)) {
        const courseId = path.split('/').pop()
        return Promise.resolve(courseDetailResponse(courseId, courseId === COURSE_A ? '课程 A' : '课程 B'))
      }
      if (path === `${API_BASE}/tasks`) {
        return Promise.resolve({ data: [taskResponse('task-a'), taskResponse('task-b', COURSE_B)] })
      }
      if (path === `${API_BASE}/tasks/task-a`) {
        taskACalls += 1
        return taskACalls === 1
          ? Promise.resolve({ data: taskResponse('task-a') })
          : laterSilentARequest.promise
      }
      if (path === `${API_BASE}/tasks/task-b`) {
        taskBCalls += 1
        return taskBCalls === 1
          ? manualBRequest.promise
          : Promise.resolve({ data: taskResponse('task-b', COURSE_B) })
      }
      throw new Error(`Unexpected API request: ${path}`)
    })

    const selector = await openCourses()
    fireEvent.change(selector, { target: { value: COURSE_B } })
    await openTasksAndRefresh()
    await screen.findByText('任务 ID：task-b')
    await waitFor(() => expect(countRequests(`${API_BASE}/tasks/task-a`)).toBe(1))

    const detailButtons = screen.getAllByRole('button', { name: '查看详情' })
    fireEvent.click(detailButtons[1])
    await waitFor(() => expect(countRequests(`${API_BASE}/tasks/task-b`)).toBe(1))
    await changePollInterval(2)
    await waitFor(() => expect(countRequests(`${API_BASE}/tasks/task-a`)).toBe(2))

    await settle(manualBRequest, { data: taskResponse('task-b', COURSE_B, 'running', [
      { id: 'b-task-video', title: 'B 任务视频' },
    ]) })
    await settle(laterSilentARequest, { data: taskResponse('task-a', COURSE_A, 'completed', [
      { id: 'a-task-video', title: 'A 任务视频' },
    ]) })

    fireEvent.click(getWorkspaceTab('任务'))
    expect(screen.getByText('状态：completed')).toBeInTheDocument()
    expect(toast.notify.mock.calls.some(([, message]) => String(message).includes('学习完成'))).toBe(true)
    fireEvent.click(getWorkspaceTab('status'))
    expect(screen.getByText('活跃任务 ID：task-b')).toBeInTheDocument()
    fireEvent.click(getWorkspaceTab('课程'))
    expect(screen.getByText('B 任务视频')).toBeInTheDocument()
    expect(screen.queryByText('A 任务视频')).not.toBeInTheDocument()
  })

  test('a pre-switch background A response updates its record and terminal notice without restoring stale B data', async () => {
    const backgroundARequest = deferred()
    let taskCalls = 0
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/config`) return Promise.resolve({ data: {} })
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
      if (path === `${API_BASE}/courses/grouped`) return Promise.resolve(courseGroupsResponse)
      if (path.startsWith(`${API_BASE}/courses/`)) {
        const courseId = path.split('/').pop()
        return Promise.resolve(courseDetailResponse(courseId, courseId === COURSE_A ? '课程 A' : '课程 B'))
      }
      if (path === `${API_BASE}/progress/${COURSE_B}`) {
        return Promise.resolve({ data: { status: 'running', message: 'B 基准进度' } })
      }
      if (path === `${API_BASE}/videos/${COURSE_B}`) {
        return Promise.resolve({ data: [{ id: 'b-video', name: 'B 基准视频' }] })
      }
      if (path === `${API_BASE}/tasks`) return Promise.resolve({ data: [taskResponse('task-a')] })
      if (path === `${API_BASE}/tasks/task-a`) {
        taskCalls += 1
        return backgroundARequest.promise
      }
      throw new Error(`Unexpected API request: ${path}`)
    })

    const initialSelector = await openCourses()
    fireEvent.change(initialSelector, { target: { value: COURSE_B } })
    fireEvent.click(screen.getByRole('button', { name: '刷新进度' }))
    fireEvent.click(screen.getByRole('button', { name: '查看视频列表/结构' }))
    await screen.findByText('B 基准视频')

    fireEvent.change(initialSelector, { target: { value: COURSE_A } })
    await openTasksAndRefresh()
    await waitFor(() => expect(taskCalls).toBe(1))

    fireEvent.click(getWorkspaceTab('课程'))
    const selector = screen.getByRole('combobox', { name: '分组课程' })
    fireEvent.change(selector, { target: { value: COURSE_B } })
    toast.notify.mockReset()
    expect(screen.queryByText('消息：B 基准进度')).not.toBeInTheDocument()
    expect(screen.queryByText('B 基准视频')).not.toBeInTheDocument()

    await settle(backgroundARequest, { data: taskResponse('task-a', COURSE_A, 'completed', [
      { id: 'a-video', title: 'A 后台视频' },
    ]) })
    fireEvent.click(getWorkspaceTab('任务'))
    expect(screen.getByText('状态：completed')).toBeInTheDocument()
    expect(toast.notify.mock.calls.some(([, message]) => String(message).includes('学习完成'))).toBe(true)

    fireEvent.click(getWorkspaceTab('课程'))
    expect(screen.queryByText('消息：B 基准进度')).not.toBeInTheDocument()
    expect(screen.queryByText('B 基准视频')).not.toBeInTheDocument()
    expect(screen.queryByText('A 后台视频')).not.toBeInTheDocument()
  })

  test('does not overlap silent requests for the same task', async () => {
    const firstSilentRequest = deferred()
    const secondSilentRequest = deferred()
    let taskCalls = 0
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/config`) return Promise.resolve({ data: {} })
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
      if (path === `${API_BASE}/courses/grouped`) return Promise.resolve(courseGroupsResponse)
      if (path.startsWith(`${API_BASE}/courses/`)) return Promise.resolve(courseDetailResponse(COURSE_A, '课程 A'))
      if (path === `${API_BASE}/tasks`) return Promise.resolve({ data: [taskResponse('task-a')] })
      if (path === `${API_BASE}/tasks/task-a`) {
        taskCalls += 1
        return taskCalls === 1 ? firstSilentRequest.promise : secondSilentRequest.promise
      }
      throw new Error(`Unexpected API request: ${path}`)
    })

    await openCourses()
    await openTasksAndRefresh()
    await waitFor(() => expect(taskCalls).toBe(1))

    await changePollInterval(2)
    expect(taskCalls).toBe(1)

    await settle(firstSilentRequest, { data: taskResponse('task-a') })
    await changePollInterval(3)
    await waitFor(() => expect(taskCalls).toBe(2))
    expect(taskCalls).toBe(2)

    await settle(secondSilentRequest, { data: taskResponse('task-a') })
  })

  test('a qr-login response cannot revive the QR session after reset', async () => {
    const qrLoginRequest = deferred()
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
      if (path === `${API_BASE}/qr-login`) return qrLoginRequest.promise
      throw new Error(`Unexpected API request: ${path}`)
    })

    renderPage()
    await flushPromises()
    fireEvent.click(screen.getByRole('button', { name: '生成二维码' }))
    await waitFor(() => expect(countRequests(`${API_BASE}/qr-login`)).toBe(1))

    fireEvent.click(getWorkspaceTab('status'))
    fireEvent.click(screen.getByRole('button', { name: '清理智慧树会话状态' }))
    await flushPromises()
    toast.notify.mockReset()

    await settle(qrLoginRequest, qrLoginResponse('session-a', 'qr-a'))
    expect(screen.getByText('二维码状态：未开始')).toBeInTheDocument()
    expect(toast.notify).not.toHaveBeenCalled()

    fireEvent.click(getWorkspaceTab('登录'))
    expect(screen.getByRole('button', { name: '生成二维码' })).toBeEnabled()
    expect(screen.queryByRole('img', { name: '智慧树二维码' })).not.toBeInTheDocument()
  })

  test.each([
    ['success', { status: 'success', message: 'A 旧成功' }],
    ['failed', { status: 'failed', message: 'A 旧失败' }],
    ['pending', { status: 'pending', message: 'A 旧等待', qr_code: 'qr-a-old' }],
  ])('an old A poll %s cannot write state, load data, or stop B polling', async (mode, response) => {
    vi.useFakeTimers()
    const oldPollRequest = deferred()
    let qrLoginCalls = 0
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
      if (path === `${API_BASE}/qr-login`) {
        qrLoginCalls += 1
        return Promise.resolve(qrLoginCalls === 1
          ? qrLoginResponse('session-a', 'qr-a', 'A 等待扫码')
          : qrLoginResponse('session-b', 'qr-b', 'B 等待扫码'))
      }
      if (path === `${API_BASE}/login-status/session-a`) return oldPollRequest.promise
      if (path === `${API_BASE}/login-status/session-b`) {
        return Promise.resolve({ status: 'pending', message: 'B 仍在等待', qr_code: 'qr-b' })
      }
      if (path === `${API_BASE}/courses/grouped`) return Promise.resolve({ data: [] })
      if (path === `${API_BASE}/config`) return Promise.resolve({ data: {} })
      if (path === `${API_BASE}/tasks`) return Promise.resolve({ data: [] })
      throw new Error(`Unexpected API request: ${path}`)
    })

    renderPage()
    await flushPromises()
    fireEvent.click(screen.getByRole('button', { name: '生成二维码' }))
    await flushPromises()
    await advanceTimers(2000)
    expect(countRequests(`${API_BASE}/login-status/session-a`)).toBe(1)

    fireEvent.click(screen.getByRole('button', { name: '生成二维码' }))
    await flushPromises()
    expect(screen.getByText('B 等待扫码')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '智慧树二维码' })).toHaveAttribute(
      'src',
      'data:image/png;base64,qr-b',
    )
    toast.notify.mockReset()

    if (mode === 'failed') {
      await fail(oldPollRequest, new Error(response.message))
    } else {
      await settle(oldPollRequest, response)
    }

    expect(screen.getByText('B 等待扫码')).toBeInTheDocument()
    expect(screen.queryByText(response.message)).not.toBeInTheDocument()
    expect(screen.getByRole('img', { name: '智慧树二维码' })).toHaveAttribute(
      'src',
      'data:image/png;base64,qr-b',
    )
    expect(countRequests(`${API_BASE}/courses/grouped`)).toBe(0)
    expect(countRequests(`${API_BASE}/config`)).toBe(0)
    expect(countRequests(`${API_BASE}/tasks`)).toBe(0)
    expect(toast.notify).not.toHaveBeenCalled()

    await advanceTimers(2000)
    expect(countRequests(`${API_BASE}/login-status/session-b`)).toBe(1)
    expect(screen.getByText('B 仍在等待')).toBeInTheDocument()
  })

  test('switching to password login prevents an old QR success from overwriting password login', async () => {
    vi.useFakeTimers()
    const oldPollRequest = deferred()
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
      if (path === `${API_BASE}/qr-login`) {
        return Promise.resolve(qrLoginResponse('session-a', 'qr-a', 'A 等待扫码'))
      }
      if (path === `${API_BASE}/login-status/session-a`) return oldPollRequest.promise
      if (path === `${API_BASE}/password-login`) {
        return Promise.resolve({ message: 'B 密码登录成功' })
      }
      if (path === `${API_BASE}/courses/grouped`) return Promise.resolve({ data: [] })
      if (path === `${API_BASE}/config`) return Promise.resolve({ data: {} })
      if (path === `${API_BASE}/tasks`) return Promise.resolve({ data: [] })
      throw new Error(`Unexpected API request: ${path}`)
    })

    renderPage()
    await flushPromises()
    fireEvent.click(screen.getByRole('button', { name: '生成二维码' }))
    await flushPromises()
    await advanceTimers(2000)
    expect(countRequests(`${API_BASE}/login-status/session-a`)).toBe(1)

    fireEvent.click(screen.getByRole('radio', { name: '账号密码登录' }))
    fireEvent.change(screen.getByLabelText('账号'), { target: { value: 'account-b' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'password-b' } })
    fireEvent.click(screen.getByRole('button', { name: '密码登录' }))
    await flushPromises()
    expect(countRequests(`${API_BASE}/password-login`)).toBe(1)
    expect(screen.getByText('智慧树状态：已登录')).toBeInTheDocument()
    expect(countRequests(`${API_BASE}/tasks`)).toBe(1)
    toast.notify.mockReset()

    await settle(oldPollRequest, { status: 'success', message: 'A 旧成功' })

    expect(countRequests(`${API_BASE}/courses/grouped`)).toBe(1)
    expect(countRequests(`${API_BASE}/config`)).toBe(1)
    expect(countRequests(`${API_BASE}/tasks`)).toBe(1)
    expect(toast.notify).not.toHaveBeenCalled()
    expect(screen.queryByText('A 旧成功')).not.toBeInTheDocument()
  })

  test('password form submission defensively invalidates an old QR rejection and leaves QR reusable', async () => {
    vi.useFakeTimers()
    const oldPollRequest = deferred()
    let qrLoginCalls = 0
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
      if (path === `${API_BASE}/qr-login`) {
        qrLoginCalls += 1
        return Promise.resolve(qrLoginCalls === 1
          ? qrLoginResponse('session-a', 'qr-a', 'A 等待扫码')
          : qrLoginResponse('session-b', 'qr-b', 'B 等待扫码'))
      }
      if (path === `${API_BASE}/login-status/session-a`) return oldPollRequest.promise
      if (path === `${API_BASE}/login-status/session-b`) {
        return Promise.resolve({ status: 'pending', message: 'B 仍在等待' })
      }
      if (path === `${API_BASE}/password-login`) {
        return Promise.resolve({ message: '密码登录成功' })
      }
      if (path === `${API_BASE}/courses/grouped`) return Promise.resolve({ data: [] })
      if (path === `${API_BASE}/config`) return Promise.resolve({ data: {} })
      if (path === `${API_BASE}/tasks`) return Promise.resolve({ data: [] })
      throw new Error(`Unexpected API request: ${path}`)
    })

    renderPage()
    await flushPromises()
    fireEvent.click(screen.getByRole('button', { name: '生成二维码' }))
    await flushPromises()
    await advanceTimers(2000)
    expect(countRequests(`${API_BASE}/login-status/session-a`)).toBe(1)

    fireEvent.click(screen.getByRole('radio', { name: '账号密码登录' }))
    fireEvent.change(screen.getByLabelText('账号'), { target: { value: 'account-b' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'password-b' } })
    fireEvent.submit(screen.getByRole('button', { name: '密码登录' }).closest('form'))
    await flushPromises()
    expect(countRequests(`${API_BASE}/password-login`)).toBe(1)
    expect(countRequests(`${API_BASE}/tasks`)).toBe(1)
    toast.notify.mockReset()

    await fail(oldPollRequest, new Error('A 旧轮询失败'))

    expect(toast.notify).not.toHaveBeenCalled()
    expect(screen.getByLabelText('账号')).toHaveValue('account-b')
    expect(screen.getByLabelText('密码')).toHaveValue('password-b')
    fireEvent.click(screen.getByRole('radio', { name: '二维码登录' }))
    expect(screen.getByText('状态：未开始')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: '智慧树二维码' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '生成二维码' }))
    await flushPromises()
    expect(screen.getByText('B 等待扫码')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '智慧树二维码' })).toHaveAttribute(
      'src',
      'data:image/png;base64,qr-b',
    )
    await advanceTimers(2000)
    expect(countRequests(`${API_BASE}/login-status/session-b`)).toBe(1)
    expect(screen.getByText('B 仍在等待')).toBeInTheDocument()
  })

  test('a slow poll has at most one request in flight for its generation', async () => {
    vi.useFakeTimers()
    const firstPollRequest = deferred()
    const secondPollRequest = deferred()
    let pollCalls = 0
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
      if (path === `${API_BASE}/qr-login`) {
        return Promise.resolve(qrLoginResponse('session-a', 'qr-a'))
      }
      if (path === `${API_BASE}/login-status/session-a`) {
        pollCalls += 1
        return pollCalls === 1 ? firstPollRequest.promise : secondPollRequest.promise
      }
      throw new Error(`Unexpected API request: ${path}`)
    })

    renderPage()
    await flushPromises()
    fireEvent.click(screen.getByRole('button', { name: '生成二维码' }))
    await flushPromises()

    await advanceTimers(6000)
    expect(pollCalls).toBe(1)

    await settle(firstPollRequest, { status: 'pending', message: '继续等待' })
    await advanceTimers(2000)
    expect(pollCalls).toBe(2)
  })

  test('QR success loads data and announces success only once', async () => {
    vi.useFakeTimers()
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
      if (path === `${API_BASE}/qr-login`) {
        return Promise.resolve(qrLoginResponse('session-a', 'qr-a'))
      }
      if (path === `${API_BASE}/login-status/session-a`) {
        return Promise.resolve({ status: 'success', message: '登录成功' })
      }
      if (path === `${API_BASE}/courses/grouped`) return Promise.resolve({ data: [] })
      if (path === `${API_BASE}/config`) return Promise.resolve({ data: {} })
      if (path === `${API_BASE}/tasks`) return Promise.resolve({ data: [] })
      throw new Error(`Unexpected API request: ${path}`)
    })

    renderPage()
    await flushPromises()
    fireEvent.click(screen.getByRole('button', { name: '生成二维码' }))
    await flushPromises()
    toast.notify.mockReset()

    await advanceTimers(2000)
    await advanceTimers(6000)

    expect(countRequests(`${API_BASE}/login-status/session-a`)).toBe(1)
    expect(countRequests(`${API_BASE}/courses/grouped`)).toBe(1)
    expect(countRequests(`${API_BASE}/config`)).toBe(1)
    expect(countRequests(`${API_BASE}/tasks`)).toBe(1)
    expect(toast.notify.mock.calls.filter(([type, message]) => (
      type === 'success' && message === '二维码登录成功，正在加载课程。'
    ))).toHaveLength(1)
  })

  test('a poll that resolves after unmount has no QR side effects', async () => {
    vi.useFakeTimers()
    const pollRequest = deferred()
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
      if (path === `${API_BASE}/qr-login`) {
        return Promise.resolve(qrLoginResponse('session-a', 'qr-a'))
      }
      if (path === `${API_BASE}/login-status/session-a`) return pollRequest.promise
      if (path === `${API_BASE}/courses/grouped`) return Promise.resolve({ data: [] })
      if (path === `${API_BASE}/config`) return Promise.resolve({ data: {} })
      if (path === `${API_BASE}/tasks`) return Promise.resolve({ data: [] })
      throw new Error(`Unexpected API request: ${path}`)
    })

    const page = renderPage()
    await flushPromises()
    fireEvent.click(screen.getByRole('button', { name: '生成二维码' }))
    await flushPromises()
    await advanceTimers(2000)
    expect(countRequests(`${API_BASE}/login-status/session-a`)).toBe(1)

    toast.notify.mockReset()
    page.unmount()
    await settle(pollRequest, { status: 'success', message: '卸载后旧成功' })

    expect(countRequests(`${API_BASE}/courses/grouped`)).toBe(0)
    expect(countRequests(`${API_BASE}/config`)).toBe(0)
    expect(countRequests(`${API_BASE}/tasks`)).toBe(0)
    expect(toast.notify).not.toHaveBeenCalled()
  })

  test.each(['reset', 'new QR', 'unmount'])(
    'QR success loaders cannot write after %s invalidates their owner',
    async (invalidation) => {
      vi.useFakeTimers()
      const coursesRequest = deferred()
      const configRequest = deferred()
      const tasksRequest = deferred()
      const nextQrLoginRequest = deferred()
      let qrLoginCalls = 0
      api.mockImplementation((path) => {
        if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
        if (path === `${API_BASE}/qr-login`) {
          qrLoginCalls += 1
          return qrLoginCalls === 1
            ? Promise.resolve(qrLoginResponse('session-a', 'qr-a'))
            : nextQrLoginRequest.promise
        }
        if (path === `${API_BASE}/login-status/session-a`) {
          return Promise.resolve({ status: 'success', message: 'A 登录成功' })
        }
        if (path === `${API_BASE}/courses/grouped`) return coursesRequest.promise
        if (path === `${API_BASE}/config`) return configRequest.promise
        if (path === `${API_BASE}/tasks`) return tasksRequest.promise
        if (path === `${API_BASE}/courses/${COURSE_A}`) {
          return Promise.resolve(courseDetailResponse(COURSE_A, '旧课程 A'))
        }
        throw new Error(`Unexpected API request: ${path}`)
      })

      const page = renderPage()
      await flushPromises()
      fireEvent.click(screen.getByRole('button', { name: '生成二维码' }))
      await flushPromises()
      await advanceTimers(2000)
      expect(countRequests(`${API_BASE}/courses/grouped`)).toBe(1)
      expect(countRequests(`${API_BASE}/config`)).toBe(1)
      expect(countRequests(`${API_BASE}/tasks`)).toBe(1)

      if (invalidation === 'reset') {
        fireEvent.click(getWorkspaceTab('status'))
        fireEvent.click(screen.getByRole('button', { name: '清理智慧树会话状态' }))
        await flushPromises()
      } else if (invalidation === 'new QR') {
        fireEvent.click(screen.getByRole('button', { name: '生成二维码' }))
        await flushPromises()
      } else {
        page.unmount()
      }
      toast.notify.mockReset()

      await settle(coursesRequest, courseGroupsResponse)
      await settle(configRequest, { data: { speed: 3, auto_answer: false } })
      await settle(tasksRequest, { data: [taskResponse('old-qr-task')] })

      expect(localStorage.getItem('zhihuishu_page_settings_v1')).toBeNull()
      expect(countRequests(`${API_BASE}/courses/${COURSE_A}`)).toBe(0)
      expect(toast.notify).not.toHaveBeenCalled()

      if (invalidation !== 'unmount') {
        fireEvent.click(getWorkspaceTab('课程'))
        expect(screen.queryByText('课程 A')).not.toBeInTheDocument()
        fireEvent.click(getWorkspaceTab('任务'))
        expect(screen.queryByText('任务 ID：old-qr-task')).not.toBeInTheDocument()
      }
      if (invalidation === 'reset') {
        fireEvent.click(getWorkspaceTab('status'))
        expect(screen.getByText('智慧树登录：未登录')).toBeInTheDocument()
      }
    },
  )

  test('an ordinary deferred course loader still applies its response', async () => {
    const coursesRequest = deferred()
    api.mockImplementation((path) => {
      if (path === `${API_BASE}/status`) return Promise.resolve({ data: { logged_in: false } })
      if (path === `${API_BASE}/courses/grouped`) return coursesRequest.promise
      if (path === `${API_BASE}/courses/${COURSE_A}`) {
        return Promise.resolve(courseDetailResponse(COURSE_A, '课程 A'))
      }
      throw new Error(`Unexpected API request: ${path}`)
    })

    renderPage()
    await flushPromises()
    fireEvent.click(getWorkspaceTab('课程'))
    fireEvent.click(screen.getByRole('button', { name: '刷新课程' }))
    await waitFor(() => expect(countRequests(`${API_BASE}/courses/grouped`)).toBe(1))

    await settle(coursesRequest, courseGroupsResponse)
    expect(screen.getByRole('combobox', { name: '分组课程' })).toHaveValue(COURSE_A)
    expect(screen.getAllByText('课程 A').length).toBeGreaterThan(0)
  })
})
