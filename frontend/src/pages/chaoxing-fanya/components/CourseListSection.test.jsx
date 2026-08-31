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
