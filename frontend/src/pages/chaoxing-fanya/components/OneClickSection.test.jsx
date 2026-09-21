import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'

import OneClickSection from './OneClickSection'


const COURSES = [
  { id: 'c1_k1_p1', courseId: 'c1', classId: 'k1', cpi: 'p1', name: '高等数学' },
  { id: 'c2_k2_p2', courseId: 'c2', classId: 'k2', cpi: 'p2', name: '大学英语' },
]

const renderSection = (overrides = {}) => {
  const props = {
    courses: COURSES,
    selectedCourses: [],
    setSelectedCourses: vi.fn(),
    startTask: vi.fn(),
    loading: false,
    authenticated: true,
    preferences: { ai_model: 'deepseek-chat' },
    hasAnswerBank: true,
    preferencesLoading: false,
    preferencesError: '',
    ...overrides,
  }
  return { props, ...render(<OneClickSection {...props} />) }
}


describe('OneClickSection', () => {
  test('stays hidden until the user is logged in', () => {
    const { container } = renderSection({ authenticated: false })
    expect(container).toBeEmptyDOMElement()
  })

  test('the button names how many courses it will take on', () => {
    renderSection()
    expect(screen.getByRole('button', { name: /一键全自动（2 门课程）/ })).toBeInTheDocument()
  })

  test('arming selects every course, so the user does not tick them one by one', async () => {
    const { props } = renderSection()
    await userEvent.click(screen.getByRole('button', { name: /一键全自动/ }))

    expect(props.setSelectedCourses).toHaveBeenCalledWith(['c1_k1_p1', 'c2_k2_p2'])
  })

  test('warns before starting when no answer bank is configured', async () => {
    renderSection({ hasAnswerBank: false, selectedCourses: ['c1_k1_p1'] })
    await userEvent.click(screen.getByRole('button', { name: /一键全自动/ }))

    // The whole point of the preflight: a run without an answer bank watches
    // videos and answers nothing, which is not what the button promises.
    expect(screen.getByRole('alert')).toHaveTextContent('不会作答任何题目')
  })

  test('a failed settings read is not reported as "not configured"', async () => {
    renderSection({ hasAnswerBank: false, preferencesError: 'boom', selectedCourses: ['c1_k1_p1'] })
    await userEvent.click(screen.getByRole('button', { name: /一键全自动/ }))

    expect(screen.getByRole('alert')).toHaveTextContent('读取已保存的答题设置失败')
    expect(screen.queryByText(/不会作答任何题目/)).not.toBeInTheDocument()
  })

  test('confirming starts the task', async () => {
    const { props } = renderSection({ selectedCourses: ['c1_k1_p1', 'c2_k2_p2'] })
    await userEvent.click(screen.getByRole('button', { name: /一键全自动/ }))
    await userEvent.click(screen.getByRole('button', { name: '确认开始' }))

    expect(props.startTask).toHaveBeenCalledTimes(1)
  })

  test('cannot start with an empty selection', async () => {
    const { props } = renderSection({ selectedCourses: [] })
    await userEvent.click(screen.getByRole('button', { name: /一键全自动/ }))

    expect(screen.getByRole('button', { name: '确认开始' })).toBeDisabled()
    expect(props.startTask).not.toHaveBeenCalled()
  })
})
