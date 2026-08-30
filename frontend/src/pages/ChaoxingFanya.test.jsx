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
    loadCourses: vi.fn(),
  },
  toast: { error: vi.fn(), success: vi.fn() },
}))

vi.mock('../components', () => ({
  useToast: () => mocks.toast,
}))

vi.mock('./chaoxing-fanya/hooks/useAuthentication', () => {
  function useMockAuthentication() {
    const [courses, setCourses] = useState(mocks.auth.courses)
    mocks.auth.setCourses = setCourses
    return { ...mocks.auth, courses, setCourses }
  }

  return { default: useMockAuthentication }
})

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

vi.mock('./chaoxing-fanya/components/LoginSection', () => ({
  default: () => (
    <button
      type="button"
      onClick={() => mocks.auth.setCourses(mocks.nextCoursesAfterEmpty || [])}
    >
      恢复课程
    </button>
  ),
}))
vi.mock('./chaoxing-fanya/components/CoursePortalSection', () => ({ default: () => null }))
vi.mock('./chaoxing-fanya/components/ConfigSection', () => ({ default: () => null }))
vi.mock('./chaoxing-fanya/components/TaskHistorySection', () => ({ default: () => null }))
vi.mock('./chaoxing-fanya/components/LogSection', () => ({ default: () => null }))
vi.mock('./chaoxing-fanya/components/CourseListSection', () => ({
  default: ({ selectedCourses, setSelectedCourses }) => (
    <>
      <output data-testid="selected-courses">{selectedCourses.join(',')}</output>
      <button type="button" onClick={() => setSelectedCourses(mocks.selection || ['course-1'])}>
        选择课程
      </button>
      <button
        type="button"
        onClick={() => {
          if (mocks.nextCourses) mocks.auth.setCourses(mocks.nextCourses)
          void mocks.auth.loadCourses()
        }}
      >
        刷新课程
      </button>
    </>
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
    mocks.auth.courses = [{ courseId: 'course-1', name: '测试课程' }]
    mocks.auth.loadCourses.mockReset()
    mocks.selection = undefined
    mocks.nextCourses = undefined
    mocks.nextCoursesAfterEmpty = undefined
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

  test.each([
    {
      name: 'partial selection keeps only the overlapping course',
      selection: ['course-a', 'course-b'],
      nextCourses: [{ courseId: 'course-b' }, { courseId: 'course-c' }],
      expectedSelection: 'course-b',
    },
    {
      name: 'all selection is cleared when the refreshed IDs are different',
      selection: ['course-a', 'course-b'],
      nextCourses: [{ courseId: 'course-c' }, { courseId: 'course-d' }],
      expectedSelection: '',
    },
  ])('$name and never submits stale IDs', async ({ selection, nextCourses, expectedSelection }) => {
    mocks.auth.courses = [{ courseId: 'course-a' }, { courseId: 'course-b' }]
    mocks.selection = selection
    mocks.nextCourses = nextCourses
    mocks.auth.callApi.mockResolvedValue({ task_id: 'task-refresh', status: 'pending' })

    const user = userEvent.setup()
    render(<ChaoxingFanya />)
    await user.click(screen.getByRole('button', { name: '选择课程' }))
    await user.click(screen.getByRole('button', { name: '刷新课程' }))

    await waitFor(() => expect(screen.getByTestId('selected-courses')).toHaveTextContent(expectedSelection))

    if (expectedSelection) {
      await user.click(screen.getByRole('button', { name: '开始刷课' }))
      await waitFor(() => expect(mocks.auth.callApi).toHaveBeenCalledWith(
        '/course/start',
        expect.objectContaining({
          body: expect.stringContaining(`"course_ids":["${expectedSelection}"]`),
        })
      ))
      const startBody = JSON.parse(mocks.auth.callApi.mock.calls.at(-1)[1].body)
      expect(startBody.course_ids).toEqual([expectedSelection])
      expect(startBody.course_ids).not.toContain('course-a')
    } else {
      await user.click(screen.getByRole('button', { name: '开始刷课' }))
      expect(mocks.auth.callApi).not.toHaveBeenCalledWith('/course/start', expect.anything())
    }
  })

  test('a failed refresh leaves the current selection untouched', async () => {
    mocks.auth.courses = [{ courseId: 'course-a' }, { courseId: 'course-b' }]
    mocks.selection = ['course-a']
    mocks.auth.loadCourses.mockResolvedValue(null)

    const user = userEvent.setup()
    render(<ChaoxingFanya />)
    await user.click(screen.getByRole('button', { name: '选择课程' }))
    await user.click(screen.getByRole('button', { name: '刷新课程' }))

    expect(screen.getByTestId('selected-courses')).toHaveTextContent('course-a')
  })

  test('an empty successful refresh clears selection before later courses are shown', async () => {
    mocks.auth.courses = [{ courseId: 'course-a' }]
    mocks.selection = ['course-a']
    mocks.nextCourses = []
    mocks.nextCoursesAfterEmpty = [{ courseId: 'course-c' }]

    const user = userEvent.setup()
    render(<ChaoxingFanya />)
    await user.click(screen.getByRole('button', { name: '选择课程' }))
    await user.click(screen.getByRole('button', { name: '刷新课程' }))
    await user.click(await screen.findByRole('button', { name: '恢复课程' }))

    await waitFor(() => expect(screen.getByTestId('selected-courses')).toBeEmptyDOMElement())
  })
})
