import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode } from 'react'
import { afterEach, describe, expect, test, vi } from 'vitest'

import CourseListSection from './CourseListSection'

const renderCourseList = (selectedCourses, loadCourses = () => Promise.resolve()) => render(
  <StrictMode>
    <CourseListSection
      courses={[{ courseId: 'course-a' }, { courseId: 'course-b' }]}
      selectedCourses={selectedCourses}
      setSelectedCourses={() => {}}
      chapters={{}}
      expanded={new Set()}
      toggleExpand={() => {}}
      loadCourses={loadCourses}
    />
  </StrictMode>,
)

const deferred = () => {
  let resolve
  const promise = new Promise((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

describe('CourseListSection selection state', () => {
  afterEach(() => {
    cleanup()
  })

  test('does not treat a same-length different ID set as all selected', () => {
    renderCourseList(['course-a', 'stale-course'])

    expect(screen.getByRole('button', { name: '全选课程' })).toBeInTheDocument()
  })

  test('treats every available course as selected regardless of selection order', () => {
    renderCourseList(['course-b', 'course-a'])

    expect(screen.getByRole('button', { name: '取消全选' })).toBeInTheDocument()
  })

  test('disables refresh while its request is pending', async () => {
    const pending = deferred()
    const loadCourses = vi.fn(() => pending.promise)
    renderCourseList([], loadCourses)
    const refreshButton = screen.getByRole('button', { name: '刷新课程' })
    const user = userEvent.setup()

    await user.click(refreshButton)

    expect(loadCourses).toHaveBeenCalledTimes(1)
    expect(refreshButton).toBeDisabled()
    expect(refreshButton).toHaveTextContent('刷新中...')

    await act(async () => {
      pending.resolve()
      await pending.promise
    })

    expect(refreshButton).not.toBeDisabled()
    expect(refreshButton).toHaveTextContent('刷新课程')
  })
})

describe('CourseListSection chapter limit picker', () => {
  const chapterList = [
    { id: 'p1', title: '1.1 绪论', has_finished: true },
    { id: 'p2', title: '1.2 基础' },
    { id: 'p3', title: '2.1 进阶', need_unlock: true },
  ]

  const renderPicker = (chapterLimits = {}, setChapterLimit = vi.fn()) => {
    render(
      <CourseListSection
        courses={[{ courseId: 'course-a', name: '高等数学' }]}
        selectedCourses={[]}
        setSelectedCourses={() => {}}
        chapters={{ 'course-a': chapterList }}
        expanded={new Set(['course-a'])}
        toggleExpand={() => {}}
        loadCourses={() => Promise.resolve()}
        chapterLimits={chapterLimits}
        setChapterLimit={setChapterLimit}
      />,
    )
    return setChapterLimit
  }

  afterEach(() => {
    cleanup()
  })

  test('defaults to studying every chapter', () => {
    renderPicker()

    expect(screen.getByRole('group', { name: '高等数学 学到哪一节' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '全部章节' })).toBeChecked()
    expect(screen.queryByText('不学')).not.toBeInTheDocument()
    expect(screen.getByText('已完成')).toBeInTheDocument()
    expect(screen.getByText('待解锁')).toBeInTheDocument()
  })

  test('choosing a chapter reports it as the last one to study', async () => {
    const setChapterLimit = renderPicker()
    const user = userEvent.setup()

    await user.click(screen.getByRole('radio', { name: /1\.2 基础/ }))

    expect(setChapterLimit).toHaveBeenCalledWith('course-a', 'p2')
  })

  test('marks chapters after the limit as skipped and summarises the choice', () => {
    renderPicker({ 'course-a': 'p2' })

    expect(screen.getByRole('radio', { name: /1\.2 基础/ })).toBeChecked()
    expect(screen.getByRole('radio', { name: '全部章节' })).not.toBeChecked()
    expect(screen.getAllByText('不学')).toHaveLength(1)
    expect(screen.getByRole('radio', { name: /2\.1 进阶/ })).toHaveAccessibleName(/不学/)
    expect(screen.getByText('学到 2/3 节：1.2 基础')).toBeInTheDocument()
  })

  test('picking 全部章节 clears the limit', async () => {
    const setChapterLimit = renderPicker({ 'course-a': 'p2' })
    const user = userEvent.setup()

    await user.click(screen.getByRole('radio', { name: '全部章节' }))

    expect(setChapterLimit).toHaveBeenCalledWith('course-a', '')
  })
})
