import { act } from 'react-dom/test-utils'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

vi.mock('../../../utils/api', () => ({
  api: vi.fn(),
  ApiError: class ApiError extends Error {},
}))

import { api } from '../../../utils/api'
import CourseListSection from './CourseListSection'

const flush = async () => {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

// getCourseId() builds `${courseId}_${classId}_${cpi}` — the exact string the
// page posts as /course/start's course_ids, so the tests assert on that shape.
const course = (n, name) => ({ courseId: String(n), classId: `c${n}`, cpi: '9', courseName: name })
const idOf = (n) => `${n}_c${n}_9`

const GROUPS = [
  { id: '10', name: '专业必修', courses: [course(1, '高等数学'), course(2, '大学物理')] },
  { id: '0', name: '我的课程', courses: [course(3, '数学建模选修')] },
]

const manyGroups = () => [
  {
    id: '10',
    name: '第一分组',
    courses: Array.from({ length: 11 }, (_, i) => course(i + 1, `课程A${i + 1}`)),
  },
  {
    id: '20',
    name: '第二分组',
    courses: Array.from({ length: 11 }, (_, i) => course(i + 100, `课程B${i + 1}`)),
  },
]

describe('CourseListSection', () => {
  let container
  let root
  let selected
  let setSelectedCourses

  const renderSection = async (props = {}) => {
    await act(async () => {
      root.render(
        <CourseListSection
          courses={props.courses || []}
          selectedCourses={props.selectedCourses || selected}
          setSelectedCourses={setSelectedCourses}
          chapters={{}}
          expanded={new Set()}
          toggleExpand={() => {}}
          loadCourses={props.loadCourses || (() => {})}
        />
      )
    })
    await flush()
  }

  const typeSearch = async (value) => {
    const input = container.querySelector('#fanya-course-search')
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
    await act(async () => {
      setter.call(input, value)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await flush()
  }

  const groupToggles = () => Array.from(container.querySelectorAll('button[aria-controls]'))

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    selected = []
    setSelectedCourses = vi.fn((next) => {
      selected = typeof next === 'function' ? next(selected) : next
    })
    api.mockReset()
    api.mockResolvedValue({ status: 'success', groups: GROUPS })
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.restoreAllMocks()
  })

  test('renders one collapsible section per group with its course count', async () => {
    await renderSection()

    expect(api).toHaveBeenCalledWith('/chaoxing/courses/grouped')
    expect(container.textContent).toContain('专业必修')
    expect(container.textContent).toContain('我的课程')
    expect(container.textContent).toContain('高等数学')

    const toggles = groupToggles()
    expect(toggles).toHaveLength(2)
    expect(toggles[0].textContent).toContain('2 门')
    expect(toggles[0].getAttribute('aria-expanded')).toBe('true')
  })

  test('falls back to the flat course list as a single section when grouping is unavailable', async () => {
    api.mockRejectedValue(Object.assign(new Error('请求失败（404）'), { status: 404 }))

    await renderSection({ courses: [course(1, '高等数学'), course(2, '大学物理')] })

    const toggles = groupToggles()
    expect(toggles).toHaveLength(1)
    expect(toggles[0].textContent).toContain('我的课程')
    expect(container.textContent).toContain('高等数学')
    expect(container.textContent).toContain('大学物理')
  })

  test('search filters by course name and drops groups with no match', async () => {
    await renderSection()
    await typeSearch('物理')

    expect(container.textContent).toContain('大学物理')
    expect(container.textContent).not.toContain('高等数学')
    // 我的课程 holds only 数学建模选修, which does not match — the group is gone.
    expect(container.textContent).not.toContain('数学建模选修')
    expect(groupToggles()).toHaveLength(1)
  })

  test('per-group 全选 selects only that group and keeps other selections', async () => {
    selected = [idOf(3)]
    await renderSection({ selectedCourses: selected })

    const selectAll = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent.trim() === '全选'
    )
    await act(async () => {
      selectAll.click()
    })

    // Still a flat array of getCourseId() strings — the selection model the
    // page's /course/start payload is built from.
    expect(selected).toEqual([idOf(3), idOf(1), idOf(2)])
  })

  test('checking a single course toggles just that id', async () => {
    await renderSection()

    const checkbox = container.querySelector('input[type="checkbox"]')
    await act(async () => {
      checkbox.click()
    })

    expect(selected).toEqual([idOf(1)])
  })

  test('collapses all but the first group when there are many courses', async () => {
    api.mockResolvedValue({ status: 'success', groups: manyGroups() })

    await renderSection()

    const toggles = groupToggles()
    expect(toggles).toHaveLength(2)
    expect(toggles[0].getAttribute('aria-expanded')).toBe('true')
    expect(toggles[1].getAttribute('aria-expanded')).toBe('false')
    expect(container.textContent).toContain('课程A1')
    expect(container.textContent).not.toContain('课程B1')

    await act(async () => {
      toggles[1].click()
    })
    expect(groupToggles()[1].getAttribute('aria-expanded')).toBe('true')
    expect(container.textContent).toContain('课程B1')
  })

  test('shows the total selected count', async () => {
    selected = [idOf(1), idOf(2)]
    await renderSection({ selectedCourses: selected })

    expect(container.textContent).toContain('共 3 门课程，已选择 2 门')
  })
})
