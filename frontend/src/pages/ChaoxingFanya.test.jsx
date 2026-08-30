import { useRef, useState } from 'react'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  auth: {
    username: 'test-user',
    password: 'test-password',
    courses: [{ courseId: 'course-1', name: '测试课程' }],
    callApi: vi.fn(),
    setError: vi.fn(),
    setNotice: vi.fn(),
  },
  toast: { error: vi.fn(), success: vi.fn() },
}))

vi.mock('../components', () => ({
  useToast: () => mocks.toast,
}))

vi.mock('./chaoxing-fanya/hooks/useAuthentication', () => ({
  default: () => mocks.auth,
}))

vi.mock('./chaoxing-fanya/hooks/useTaskExecution', () => ({
  default: function MockTaskExecution() {
    const [taskId, setTaskId] = useState('')
    const [taskStatus, setTaskStatus] = useState(null)
    const [loading, setLoading] = useState(false)
    const [logs, setLogs] = useState([])
    const [logCursor, setLogCursor] = useState(0)
    const [taskHistory, setTaskHistory] = useState([])
    const logCursorRef = useRef(0)

    return {
      taskId,
      setTaskId,
      taskStatus,
      setTaskStatus,
      loading,
      setLoading,
      logs,
      setLogs,
      logCursor,
      setLogCursor,
      logCursorRef,
      taskHistory,
      setTaskHistory,
      appendLogs: vi.fn(),
      controlTask: vi.fn(),
      selectTaskFromHistory: vi.fn(),
    }
  },
}))

vi.mock('./chaoxing-fanya/components/LoginSection', () => ({ default: () => null }))
vi.mock('./chaoxing-fanya/components/CoursePortalSection', () => ({ default: () => null }))
vi.mock('./chaoxing-fanya/components/ConfigSection', () => ({ default: () => null }))
vi.mock('./chaoxing-fanya/components/TaskHistorySection', () => ({ default: () => null }))
vi.mock('./chaoxing-fanya/components/LogSection', () => ({ default: () => null }))
vi.mock('./chaoxing-fanya/components/CourseListSection', () => ({
  default: ({ setSelectedCourses }) => (
    <button type="button" onClick={() => setSelectedCourses(['course-1'])}>
      选择课程
    </button>
  ),
}))

import ChaoxingFanya from './ChaoxingFanya'

const selectCourseAndStart = async () => {
  const user = userEvent.setup()
  render(<ChaoxingFanya />)
  await user.click(screen.getByRole('button', { name: '选择课程' }))
  const startButton = screen.getByRole('button', { name: '开始刷课' })
  await user.click(startButton)
}

describe('ChaoxingFanya start task loading state', () => {
  beforeEach(() => {
    mocks.auth.callApi.mockReset()
    mocks.auth.setError.mockReset()
    mocks.auth.setNotice.mockReset()
    mocks.toast.error.mockReset()
    mocks.toast.success.mockReset()
  })

  afterEach(() => {
    cleanup()
  })

  test.each(['running', 'pending'])('clears loading after a %s task is accepted while keeping the task disabled', async (status) => {
    mocks.auth.callApi.mockResolvedValue({ task_id: `task-${status}`, status })

    await selectCourseAndStart()

    const startButton = screen.getByRole('button', { name: '开始刷课' })
    await waitFor(() => expect(startButton).toBeDisabled())
    expect(screen.queryByText('启动中...')).not.toBeInTheDocument()
  })

  test('clears loading after an empty response', async () => {
    mocks.auth.callApi.mockResolvedValue(null)

    await selectCourseAndStart()

    await waitFor(() => expect(screen.getByRole('button', { name: '开始刷课' })).toBeEnabled())
    expect(screen.queryByText('启动中...')).not.toBeInTheDocument()
  })

  test('clears loading after a start request error', async () => {
    mocks.auth.callApi.mockRejectedValue(new Error('network failure'))

    await selectCourseAndStart()

    await waitFor(() => expect(screen.getByRole('button', { name: '开始刷课' })).toBeEnabled())
    expect(screen.queryByText('启动中...')).not.toBeInTheDocument()
    expect(mocks.auth.setError).toHaveBeenCalledWith('network failure')
  })
})
