import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'

import CourseListSection from './CourseListSection'

const renderCourseList = (selectedCourses) => render(
  <CourseListSection
    courses={[{ courseId: 'course-a' }, { courseId: 'course-b' }]}
    selectedCourses={selectedCourses}
    setSelectedCourses={() => {}}
    chapters={{}}
    expanded={new Set()}
    toggleExpand={() => {}}
    loadCourses={() => Promise.resolve()}
  />
)

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
})
