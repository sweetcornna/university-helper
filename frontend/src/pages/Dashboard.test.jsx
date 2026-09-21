import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'

import { RuntimeProfileContext } from '../components/runtimeProfileContext'
import { api } from '../utils/api'
import Dashboard from './Dashboard'

vi.mock('../utils/api', () => ({ api: vi.fn() }))

const CASES = [
  {
    name: '签到运行任务',
    status: 'running',
    statusLabel: '进行中',
    serviceTitle: '学习通签到',
    targetPath: '/chaoxing-signin',
    targetHeading: '签到页面',
    signinTasks: [{ status: 'running', course_name: '签到课程' }],
    fanyaTasks: [],
    zhihuishuTasks: [],
  },
  {
    name: '智慧树运行任务',
    status: 'running',
    statusLabel: '进行中',
    serviceTitle: '智慧树',
    targetPath: '/zhihuishu-panel',
    targetHeading: '智慧树页面',
    signinTasks: [],
    fanyaTasks: [],
    zhihuishuTasks: [{ status: 'running', course_name: '智慧树课程' }],
  },
  {
    name: '泛雅运行任务',
    status: 'running',
    statusLabel: '进行中',
    serviceTitle: '学习通泛雅',
    targetPath: '/chaoxing-fanya',
    targetHeading: '泛雅页面',
    signinTasks: [],
    fanyaTasks: [{ status: 'running', course_name: '泛雅课程' }],
    zhihuishuTasks: [],
  },
  {
    name: '签到失败任务',
    status: 'failed',
    statusLabel: '失败',
    serviceTitle: '学习通签到',
    targetPath: '/chaoxing-signin',
    targetHeading: '签到页面',
    signinTasks: [{ status: 'failed', course_name: '签到课程' }],
    fanyaTasks: [],
    zhihuishuTasks: [],
  },
  {
    name: '智慧树失败任务',
    status: 'failed',
    statusLabel: '失败',
    serviceTitle: '智慧树',
    targetPath: '/zhihuishu-panel',
    targetHeading: '智慧树页面',
    signinTasks: [],
    fanyaTasks: [],
    zhihuishuTasks: [{ status: 'failed', course_name: '智慧树课程' }],
  },
  {
    name: '泛雅失败任务',
    status: 'failed',
    statusLabel: '失败',
    serviceTitle: '学习通泛雅',
    targetPath: '/chaoxing-fanya',
    targetHeading: '泛雅页面',
    signinTasks: [],
    fanyaTasks: [{ status: 'failed', course_name: '泛雅课程' }],
    zhihuishuTasks: [],
  },
]

function RouteProbe() {
  const location = useLocation()
  return <output aria-label="当前路径">{location.pathname}</output>
}

const renderDashboard = () =>
  render(
    <RuntimeProfileContext.Provider
      value={{ profile: 'local', isLocal: true, requiresAuth: false, loading: false }}
    >
      <MemoryRouter
        initialEntries={['/dashboard']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <RouteProbe />
        <Routes>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/chaoxing-signin" element={<h1>签到页面</h1>} />
          <Route path="/zhihuishu-panel" element={<h1>智慧树页面</h1>} />
          <Route path="/chaoxing-fanya" element={<h1>泛雅页面</h1>} />
        </Routes>
      </MemoryRouter>
    </RuntimeProfileContext.Provider>
  )

const mockTaskRequests = ({ signin = [], fanya = [], zhihuishu = [], reject = [] } = {}) => {
  api.mockImplementation((path) => {
    if (reject.includes(path)) return Promise.reject(new Error(`${path} unavailable`))
    if (path === '/chaoxing/task-list') return Promise.resolve({ data: signin })
    if (path === '/course/tasks') return Promise.resolve({ tasks: fanya })
    if (path === '/course/zhihuishu/tasks') {
      return Promise.resolve({ data: { tasks: zhihuishu } })
    }
    return Promise.reject(new Error(`Unexpected API path: ${path}`))
  })
}

const expectTaskRequests = () => {
  expect(api).toHaveBeenCalledWith('/chaoxing/task-list', {
    method: 'GET',
    timeoutMs: 6000,
  })
  expect(api).toHaveBeenCalledWith('/course/tasks', {
    method: 'GET',
    timeoutMs: 6000,
  })
  expect(api).toHaveBeenCalledWith('/course/zhihuishu/tasks', {
    method: 'GET',
    timeoutMs: 6000,
  })
}

describe('Dashboard task routing', () => {
  beforeEach(() => {
    api.mockReset()
  })

  test.each(CASES)('routes $name to its service', async (testCase) => {
    mockTaskRequests({
      signin: testCase.signinTasks,
      fanya: testCase.fanyaTasks,
      zhihuishu: testCase.zhihuishuTasks,
    })

    const user = userEvent.setup()
    renderDashboard()

    const actionLabel = testCase.status === 'failed' ? '前往恢复' : '查看任务'
    await screen.findByRole('button', { name: actionLabel })
    const serviceButton = screen.getByRole('button', { name: testCase.serviceTitle })
    expect(within(serviceButton).getByText(testCase.statusLabel)).toBeTruthy()

    await user.click(screen.getByRole('button', { name: actionLabel }))

    expect(
      screen.getByRole('heading', { level: 1, name: testCase.targetHeading })
    ).toBeTruthy()
    expectTaskRequests()
    expect(screen.getByLabelText('当前路径')).toHaveTextContent(testCase.targetPath)
  })

  test('selects the newest failed task across services', async () => {
    mockTaskRequests({
      fanya: [
        {
          status: 'failed',
          course_name: '较早失败',
          updated_at: '2026-07-29T08:00:00Z',
        },
      ],
      zhihuishu: [
        {
          status: 'failed',
          course_name: '最新失败',
          updatedAt: '2026-07-29T09:00:00Z',
        },
      ],
    })

    const user = userEvent.setup()
    renderDashboard()

    const action = await screen.findByRole('button', { name: '前往恢复' })
    const nextAction = screen.getByRole('heading', { level: 2, name: '处理最近失败' }).closest('section')
    expect(within(nextAction).getByText(/智慧树 · 最新失败/)).toBeTruthy()
    expect(screen.getAllByText(/智慧树 · 最新失败/, { selector: 'p' })).toHaveLength(2)
    expect(screen.queryByText(/学习通泛雅 · 较早失败/, { selector: 'p' })).toBeNull()

    await user.click(action)
    expect(screen.getByLabelText('当前路径')).toHaveTextContent('/zhihuishu-panel')
  })

  test('reports a partial sync when only some services fulfill', async () => {
    mockTaskRequests({
      reject: ['/course/tasks'],
    })
    renderDashboard()

    expect(await screen.findByText('部分不可用')).toHaveAttribute('role', 'status')
    expectTaskRequests()
  })

  test('shows only the service grid when no active or failed task exists', async () => {
    mockTaskRequests()
    renderDashboard()

    expect(await screen.findByText('已同步任务')).toHaveAttribute('role', 'status')
    expect(screen.queryByRole('heading', { level: 2, name: /查看运行进度|处理最近失败|选择课程服务/ })).toBeNull()
    expect(screen.queryByText('待进入')).toBeNull()
    expect(screen.queryByText('打开服务')).toBeNull()
    expect(screen.queryByText('开放')).toBeNull()
    expect(screen.queryByText('暂无运行任务')).toBeNull()
    expect(screen.queryByText('没有待处理失败')).toBeNull()
    expect(screen.getByRole('button', { name: '学习通签到' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '学习通泛雅' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '智慧树' })).toBeTruthy()
  })
})
