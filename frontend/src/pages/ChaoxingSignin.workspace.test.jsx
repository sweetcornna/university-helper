import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { RuntimeProfileContext } from '../components/runtimeProfileContext'
import { ToastProvider } from '../components'
import ChaoxingSignin from './ChaoxingSignin'

const response = (payload, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  text: async () => JSON.stringify(payload),
})

function CurrentLocation() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}{location.search}</output>
}

function renderPage(entry = '/chaoxing-signin') {
  return render(
    <RuntimeProfileContext.Provider value={{ isLocal: false, loading: false }}>
      <ToastProvider>
        <MemoryRouter initialEntries={[entry]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <ChaoxingSignin />
          <CurrentLocation />
        </MemoryRouter>
      </ToastProvider>
    </RuntimeProfileContext.Provider>
  )
}

async function verifyAccount(user, username = 'student', password = 'password') {
  await user.type(screen.getByLabelText('账号 / 手机号'), username)
  await user.type(screen.getByLabelText('密码'), password)
  await user.click(screen.getByRole('button', { name: '验证账号并获取课程' }))
  await screen.findByRole('button', { name: `平台账号：${username}` })
}

const requestedPaths = () => fetch.mock.calls.map(([input]) => String(input).split('?')[0].split('/').pop())

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  sessionStorage.setItem('auth_token', 'app-token')
  vi.stubGlobal('fetch', vi.fn(async () => response({ status: true, data: [] })))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Chaoxing sign-in workspaces', () => {
  test('fresh load shows only the account card without detecting sign-ins', async () => {
    renderPage()
    expect(screen.getByRole('button', { name: '平台账号：未登录' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '验证账号并获取课程' })).toBeInTheDocument()
    await waitFor(() => expect(requestedPaths()).toContain('task-list'))
    expect(requestedPaths()).not.toEqual(expect.arrayContaining(['tasks']))
    expect(requestedPaths()).not.toEqual(expect.arrayContaining(['courses']))
    expect(requestedPaths()).not.toEqual(expect.arrayContaining(['classes']))
    expect(screen.queryByLabelText('签到类型')).not.toBeInTheDocument()
    expect(screen.queryByRole('group', { name: '签到范围' })).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  test('keeps account fields editable until verification and retains them across sections', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.type(screen.getByLabelText('账号 / 手机号'), 'student')
    await user.type(screen.getByLabelText('密码'), 'full-password')
    expect(screen.getByLabelText('密码')).toHaveValue('full-password')
    await user.click(screen.getByRole('tab', { name: '自动监控' }))
    expect(screen.queryByLabelText('密码')).not.toBeInTheDocument()
    expect(screen.queryByText('后台任务历史')).not.toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: '账号' }))
    expect(screen.getByLabelText('密码')).toHaveValue('full-password')
    await user.click(screen.getByRole('button', { name: '验证账号并获取课程' }))
    await waitFor(() => expect(screen.getByRole('tab', { name: '手动签到' })).toHaveAttribute('aria-selected', 'true'))
    expect(screen.queryByLabelText('密码')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '平台账号：student' })).toBeInTheDocument()
  })

  test.each([
    [401, '学习通登录已失效，请在平台账号中重新登录学习通。'],
    [502, '签到检测服务暂不可用，请稍后重试。'],
  ])('shows a %s detection error without clearing the app session or claiming no activities', async (status, detail) => {
    const user = userEvent.setup()
    fetch.mockImplementation(async (input) => String(input).endsWith('/tasks')
      ? response({ detail }, status)
      : response({ status: true, data: [] }))
    renderPage()
    await verifyAccount(user)
    expect(await screen.findByText('签到检测未完成')).toBeInTheDocument()
    expect(screen.getByText(detail)).toBeInTheDocument()
    expect(screen.queryByText('未检测到进行中的签到')).not.toBeInTheDocument()
    expect(sessionStorage.getItem('auth_token')).toBe('app-token')
    expect(screen.getByTestId('location')).toHaveTextContent('/chaoxing-signin')
  })

  test('redirects only an app JWT expiry to app login', async () => {
    fetch.mockImplementation(async () => response({ detail: 'Invalid token' }, 401))
    renderPage()
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/login'))
    expect(sessionStorage.getItem('auth_token')).toBeNull()
  })

  test('keeps the old config deep link and moves history out of manual sign-in', async () => {
    const user = userEvent.setup()
    renderPage('/chaoxing-signin?tab=config')
    expect(screen.getByRole('tab', { name: '自动监控' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('switch', { name: '自动签到' })).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: '签到记录' }))
    expect(screen.getByText('后台任务历史')).toBeInTheDocument()
    expect(screen.queryByRole('switch', { name: '自动签到' })).not.toBeInTheDocument()
  })

  test('ignores a previous account\'s late responses after re-verification and describes a verified empty account', async () => {
    const user = userEvent.setup()
    const initialRequests = []
    const requestCounts = new Map()
    fetch.mockImplementation(async (input) => {
      const path = String(input).split('/').pop()
      const count = (requestCounts.get(path) || 0) + 1
      requestCounts.set(path, count)
      if (['courses', 'classes', 'tasks'].includes(path) && count === 1) {
        return new Promise((resolve) => initialRequests.push({ path, resolve }))
      }
      return response({ status: true, data: [] })
    })
    renderPage()
    await verifyAccount(user, 'old-account')
    await user.click(screen.getByRole('tab', { name: '账号' }))
    await user.clear(screen.getByLabelText('账号 / 手机号'))
    await user.type(screen.getByLabelText('账号 / 手机号'), 'empty-account')
    await user.click(screen.getByRole('button', { name: '验证账号并获取课程' }))
    await screen.findByRole('button', { name: '平台账号：empty-account' })
    expect(await screen.findByText('此账号暂无课程；可在学习通加入课程后刷新')).toBeInTheDocument()
    await act(async () => {
      initialRequests.forEach(({ path, resolve }) => resolve(response({ data: path === 'tasks'
        ? [{ courseName: '旧账号签到', type: 'normal', actionable: true }]
        : [{ courseId: 'old-course', classId: 'old-class', name: '旧账号课程' }] })))
    })
    expect(screen.queryByText('旧账号课程')).not.toBeInTheDocument()
    expect(screen.queryByText('旧账号签到')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '班级' }))
    expect(screen.getByText('此账号暂无班级；可在学习通加入班级后刷新')).toBeInTheDocument()
  })

  test('submits a parsed group activity with credentials and keeps course settings intact', async () => {
    const user = userEvent.setup()
    renderPage()
    await verifyAccount(user)
    await user.selectOptions(screen.getByLabelText('签到类型'), 'photo')
    await user.click(screen.getByRole('button', { name: '群聊' }))
    expect(screen.queryByLabelText('签到类型')).not.toBeInTheDocument()
    expect(screen.getByText(/支持普通签到和位置签到/)).toBeInTheDocument()
    await user.type(screen.getByLabelText('活动链接（可选）'), 'https://mobilelearn.chaoxing.com/pptSign/stuSign?aid=123&chatId=456')
    await user.click(screen.getByRole('button', { name: '解析活动链接' }))
    expect(screen.getByLabelText('群聊 ID')).toHaveValue('456')
    expect(screen.getByLabelText('活动 ID')).toHaveValue('123')
    await user.click(screen.getByRole('button', { name: '提交群聊签到' }))
    await waitFor(() => expect(fetch.mock.calls.some(([input]) => String(input).endsWith('/chat-sign'))).toBe(true))
    const calls = fetch.mock.calls.filter(([input]) => String(input).endsWith('/chat-sign'))
    expect(calls).toHaveLength(1)
    expect(JSON.parse(calls[0][1].body)).toEqual({ username: 'student', password: 'password', chat_id: '456', active_id: '123' })
    await user.click(screen.getByRole('button', { name: '课程' }))
    expect(screen.getByLabelText('签到类型')).toHaveValue('photo')
  })

  test('a group location sign-in asks for a position and resubmits with the chosen coordinates', async () => {
    const user = userEvent.setup()
    fetch.mockImplementation(async (input, init) => {
      if (!String(input).endsWith('/chat-sign')) return response({ status: true, data: [] })
      return JSON.parse(init.body).latitude === undefined
        ? response({ status: false, message: '这是位置签到，请先设置签到位置（地图选点或使用当前位置）后再提交。', data: { requiresLocation: true } })
        : response({ status: true, message: 'success' })
    })
    renderPage()
    await verifyAccount(user)
    await user.click(screen.getByRole('button', { name: '群聊' }))
    expect(screen.queryByRole('group', { name: '签到位置' })).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('群聊 ID'), '456')
    await user.type(screen.getByLabelText('活动 ID'), '123')
    await user.click(screen.getByRole('button', { name: '提交群聊签到' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('这是位置签到')
    expect(screen.getByRole('group', { name: '签到位置' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '提交群聊签到' }))
    expect(screen.getByRole('alert')).toHaveTextContent('这是位置签到')
    expect(fetch.mock.calls.filter(([input]) => String(input).endsWith('/chat-sign'))).toHaveLength(1)

    fireEvent.change(screen.getByLabelText('纬度'), { target: { value: '39.9087' } })
    fireEvent.change(screen.getByLabelText('经度'), { target: { value: '116.3975' } })
    await user.click(screen.getByRole('button', { name: '提交群聊签到' }))
    await screen.findByText('群聊签到成功。')
    const calls = fetch.mock.calls.filter(([input]) => String(input).endsWith('/chat-sign'))
    expect(calls).toHaveLength(2)
    expect(JSON.parse(calls[1][1].body)).toMatchObject({ chat_id: '456', active_id: '123', latitude: 39.9087, longitude: 116.3975 })
  })

  test.each(['photo', 'unknown'])('detects group activities, exposes scope warnings and blocks %s activity submission', async (type) => {
    const user = userEvent.setup()
    fetch.mockImplementation(async (input) => String(input).includes('/chat-activities')
      ? response({ status: true, data: [{ chatId: '456', activeId: '123', name: '待核对的群内活动', type }], warnings: ['仅检查最近会话中的最新消息。'], scope: 'latest_messages' })
      : response({ status: true, data: [] }))
    renderPage()
    await verifyAccount(user)
    await user.click(screen.getByRole('button', { name: '群聊' }))
    await user.type(screen.getByLabelText('群聊 ID'), '456')
    await user.click(screen.getByRole('button', { name: '检测群聊活动' }))
    await screen.findByText('待核对的群内活动')
    expect(fetch).toHaveBeenCalledWith('/api/v1/chaoxing/chat-activities?chat_id=456', expect.objectContaining({ method: 'GET' }))
    expect(screen.getByText('仅检查最近会话中的最新消息。')).toBeInTheDocument()
    expect(screen.getByText(type === 'photo' ? /拍照签到 · 暂不支持/ : /未知类型 · 暂不支持/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '选择此活动' }))
    expect(screen.getByLabelText('活动 ID')).toHaveValue('123')
    expect(screen.getByRole('button', { name: '提交群聊签到' })).toBeDisabled()
    expect(fetch.mock.calls.filter(([input]) => String(input).endsWith('/chat-sign'))).toHaveLength(0)
  })

  test('rejects non-official group links and surfaces server type rejection without success feedback', async () => {
    const user = userEvent.setup()
    fetch.mockImplementation(async (input) => String(input).endsWith('/chat-sign')
      ? response({ status: false, message: '此活动需要照片，请在学习通 App 完成。' })
      : response({ status: true, data: [] }))
    renderPage()
    await verifyAccount(user)
    await user.click(screen.getByRole('button', { name: '群聊' }))
    await user.type(screen.getByLabelText('活动链接（可选）'), 'https://example.com/sign?aid=123&chatId=456')
    await user.click(screen.getByRole('button', { name: '提交群聊签到' }))
    expect(screen.getByRole('alert')).toHaveTextContent('官方活动链接')
    expect(fetch.mock.calls.filter(([input]) => String(input).endsWith('/chat-sign'))).toHaveLength(0)
    await user.clear(screen.getByLabelText('活动链接（可选）'))
    await user.type(screen.getByLabelText('群聊 ID'), '456')
    await user.type(screen.getByLabelText('活动 ID'), '123')
    await user.click(screen.getByRole('button', { name: '提交群聊签到' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('此活动需要照片')
    expect(screen.queryByText('群聊签到成功。')).not.toBeInTheDocument()
  })

  test('group detection failures remain errors and late responses cannot restore another group', async () => {
    const user = userEvent.setup()
    let resolveDetection
    fetch.mockImplementation(async (input) => String(input).includes('/chat-activities')
      ? new Promise((resolve) => { resolveDetection = resolve })
      : response({ status: true, data: [] }))
    renderPage()
    await verifyAccount(user)
    await user.click(screen.getByRole('button', { name: '群聊' }))
    await user.type(screen.getByLabelText('群聊 ID'), '456')
    await user.click(screen.getByRole('button', { name: '检测群聊活动' }))
    await user.clear(screen.getByLabelText('群聊 ID'))
    await user.type(screen.getByLabelText('群聊 ID'), '789')
    await act(async () => resolveDetection(response({ data: { tasks: [{ chatId: '456', activeId: '123', name: '旧群活动', type: 'normal' }] } })))
    expect(screen.queryByText('旧群活动')).not.toBeInTheDocument()
    fetch.mockImplementation(async () => response({ detail: '群聊检测服务暂不可用，请重试。' }, 502))
    await user.click(screen.getByRole('button', { name: '检测群聊活动' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('群聊检测服务暂不可用')
    expect(screen.queryByText(/未检测到群聊活动/)).not.toBeInTheDocument()
  })

  test('manual course submission sends only selected course selectors', async () => {
    const user = userEvent.setup()
    fetch.mockImplementation(async (input) => {
      if (String(input).endsWith('/courses')) return response({ data: [{ courseId: '1', classId: '10', name: '课程一' }, { courseId: '2', classId: '20', name: '课程二' }] })
      return response({ status: true, data: [] })
    })
    renderPage()
    await verifyAccount(user)
    await screen.findByText('课程一')
    await user.click(screen.getByRole('checkbox', { name: /课程一/ }))
    await user.click(screen.getByRole('button', { name: '课程签到', exact: true }))
    await waitFor(() => expect(fetch.mock.calls.some(([input]) => String(input).endsWith('/sign'))).toBe(true))
    const calls = fetch.mock.calls.filter(([input]) => String(input).endsWith('/sign'))
    expect(calls).toHaveLength(1)
    expect(JSON.parse(calls[0][1].body).course_id).toBe('1_10')
  })
})
