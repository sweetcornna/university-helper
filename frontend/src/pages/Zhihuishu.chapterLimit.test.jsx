import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { ToastProvider } from '../components/Toast'
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

const COURSE_TASK_PATH = '/course/zhihuishu/tasks/course'
const VIDEOS_PATH = '/course/zhihuishu/videos/course-1'

const course = {
  courseId: 'course-1',
  name: '高等数学',
}

const video = (id, chapterId, chapterTitle) => ({
  id,
  title: `视频 ${id}`,
  status: 'pending',
  chapter_id: chapterId,
  chapter_title: chapterTitle,
})

const FULL_COURSE = [
  video('v1', 'ch1', '第一章 函数'),
  video('v2', 'ch1', '第一章 函数'),
  video('v3', 'ch2', '第二章 极限'),
  video('v4', 'ch3', '第三章 导数'),
]

const renderPage = () => render(
  <ToastProvider>
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Zhihuishu />
    </MemoryRouter>
  </ToastProvider>,
)

const configureApi = (videoLists) => {
  const queue = [...videoLists]
  api.mockImplementation((path, options = {}) => {
    if (path === '/course/zhihuishu/status') return Promise.resolve({ data: { logged_in: false } })
    if (path === '/course/zhihuishu/config') return Promise.resolve({ data: { speed: 1, auto_answer: true } })
    if (path === '/course/zhihuishu/courses/grouped') {
      return Promise.resolve({ data: [{ group: '本学期', courses: [course] }] })
    }
    if (path === '/course/zhihuishu/courses/course-1') return Promise.resolve({ data: course })
    if (path === VIDEOS_PATH) {
      const list = queue.length > 1 ? queue.shift() : queue[0]
      return Promise.resolve({ status: 'success', data: list })
    }
    if (path.startsWith('/course/zhihuishu/tasks/') && options.method === 'GET') return new Promise(() => {})
    if (path === COURSE_TASK_PATH) {
      return Promise.resolve({ task_id: 'task-1', course_id: course.courseId, status: 'running' })
    }
    return Promise.resolve({})
  })
}

const startBody = () => {
  const call = api.mock.calls.find(([path, options]) => path === COURSE_TASK_PATH && options?.method === 'POST')
  return call ? JSON.parse(call[1].body) : null
}

const openCourse = async () => {
  fireEvent.click(await screen.findByText('课程', { selector: 'button' }))
  fireEvent.click(await screen.findByRole('button', { name: '刷新课程' }))
  const selector = await screen.findByRole('combobox', { name: '分组课程' })
  await waitFor(() => expect(selector).toHaveValue(course.courseId))
}

const loadChapters = async () => {
  fireEvent.click(screen.getByRole('button', { name: '加载章节' }))
  await waitFor(() => expect(screen.getByRole('combobox', { name: '学到哪一章' })).toBeEnabled())
  return screen.getByRole('combobox', { name: '学到哪一章' })
}

const clickStart = async () => {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: /启动课程任务/ }))
    await Promise.resolve()
  })
  await waitFor(() => expect(startBody()).not.toBeNull())
}

describe('Zhihuishu 学到哪一章', () => {
  beforeEach(() => {
    localStorage.clear()
    api.mockReset()
  })

  afterEach(() => {
    vi.clearAllTimers()
  })

  test('is disabled until the chapters are loaded', async () => {
    configureApi([FULL_COURSE])
    renderPage()
    await openCourse()

    expect(screen.getByRole('combobox', { name: '学到哪一章' })).toBeDisabled()
    expect(screen.getByText('默认学完整门课。想只学一部分，先加载章节再选。')).toBeInTheDocument()
  })

  test('sends the chosen last chapter with the start request', async () => {
    configureApi([FULL_COURSE])
    renderPage()
    await openCourse()

    const select = await loadChapters()
    expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual(
      expect.arrayContaining(['全部章节', '1. 第一章 函数（2 个视频）', '2. 第二章 极限（1 个视频）', '3. 第三章 导数（1 个视频）'])
    )

    fireEvent.change(select, { target: { value: 'ch2' } })
    expect(screen.getByText('只学到第 2 章（含），共 3 个视频；后面 1 章不学。')).toBeInTheDocument()

    await clickStart()
    expect(startBody()).toMatchObject({ course_id: 'course-1', end_chapter_id: 'ch2' })
  })

  test('studies the whole course when 全部章节 is kept', async () => {
    configureApi([FULL_COURSE])
    renderPage()
    await openCourse()
    await loadChapters()

    await clickStart()
    expect(startBody()).not.toHaveProperty('end_chapter_id')
  })

  test('drops a choice whose chapter is gone after reloading', async () => {
    configureApi([FULL_COURSE, FULL_COURSE.filter((item) => item.chapter_id !== 'ch3')])
    renderPage()
    await openCourse()

    const select = await loadChapters()
    fireEvent.change(select, { target: { value: 'ch3' } })
    expect(select).toHaveValue('ch3')

    fireEvent.click(screen.getByRole('button', { name: '查看视频列表/结构' }))
    await waitFor(() => expect(select).toHaveValue(''))

    await clickStart()
    expect(startBody()).not.toHaveProperty('end_chapter_id')
  })
})
