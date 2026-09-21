import { act } from 'react-dom/test-utils'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import TaskHistorySection from './TaskHistorySection'
import { labelTaskHistory, taskStatusLabel, toChineseNumeral } from '../utils'

// The list used to print raw `task_id`s — 32-char hex strings — newest-first by
// accident of insertion order. These pin the two things a reader needs: a real
// time order, and a label that can be spoken out loud.

const task = (id, updatedAt, status = 'failed') => ({
  task_id: id,
  updated_at: updatedAt,
  status,
})

describe('labelTaskHistory', () => {
  test('orders newest first', () => {
    const rows = labelTaskHistory([
      task('old', '2026-07-12T22:03:33+00:00'),
      task('new', '2026-09-20T19:56:33+00:00'),
      task('mid', '2026-09-20T19:56:16+00:00'),
    ])

    expect(rows.map((row) => row.task_id)).toEqual(['new', 'mid', 'old'])
  })

  test('labels run 任务一, 任务二, … in display order', () => {
    const rows = labelTaskHistory([
      task('a', '2026-07-12T22:03:33+00:00'),
      task('b', '2026-09-20T19:56:33+00:00'),
    ])

    expect(rows[0].label).toBe('任务一')
    expect(rows[1].label).toBe('任务二')
  })

  test('keeps every original field', () => {
    const [row] = labelTaskHistory([task('abc', '2026-09-20T19:56:33+00:00')])

    expect(row.task_id).toBe('abc')
    expect(row.status).toBe('failed')
  })

  test('tolerates a missing or malformed timestamp', () => {
    const rows = labelTaskHistory([
      { task_id: 'no-time', status: 'failed' },
      task('bad', 'not-a-date'),
      task('good', '2026-09-20T19:56:33+00:00'),
    ])

    // Anything undateable sorts last rather than throwing.
    expect(rows[0].task_id).toBe('good')
  })

  test('handles an empty or absent list', () => {
    expect(labelTaskHistory([])).toEqual([])
    expect(labelTaskHistory(undefined)).toEqual([])
  })
})

describe('toChineseNumeral', () => {
  test.each([
    [1, '一'],
    [3, '三'],
    [9, '九'],
    [10, '十'],
    [11, '十一'],
    [20, '二十'],
    [21, '二十一'],
    [99, '九十九'],
    // Past 99 a Chinese numeral is unreadable, so the plain number is returned.
    [100, '100'],
  ])('%i -> %s', (input, expected) => {
    expect(toChineseNumeral(input)).toBe(expected)
  })
})

describe('taskStatusLabel', () => {
  test('translates the statuses the backend emits', () => {
    expect(taskStatusLabel('failed')).toBe('失败')
    expect(taskStatusLabel('completed')).toBe('已完成')
    expect(taskStatusLabel('running')).toBe('运行中')
    expect(taskStatusLabel('PAUSED')).toBe('已暂停')
  })

  test('falls through to the raw value for an unknown status', () => {
    expect(taskStatusLabel('weird')).toBe('weird')
    expect(taskStatusLabel(undefined)).toBe('未知')
  })
})

describe('TaskHistorySection', () => {
  let container
  let root

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  const render = (taskHistory, selectTaskFromHistory = vi.fn()) =>
    act(() => {
      root.render(
        <TaskHistorySection
          taskHistory={taskHistory}
          taskId=""
          selectTaskFromHistory={selectTaskFromHistory}
        />
      )
    })

  test('shows readable labels instead of raw task ids', () => {
    render([
      task('8eb2a1964f474d94af41f6ce8c4a93ed', '2026-09-20T19:56:33+00:00'),
      task('edfd8d7044b646ad9f167fdf2ade470e', '2026-07-12T22:03:33+00:00'),
    ])

    expect(container.textContent).toContain('任务一')
    expect(container.textContent).toContain('任务二')
    // The hex id must not appear as visible text...
    expect(container.textContent).not.toContain('8eb2a1964f474d94af41f6ce8c4a93ed')
    // ...but stays recoverable for debugging.
    expect(container.querySelector('[title="8eb2a1964f474d94af41f6ce8c4a93ed"]')).not.toBeNull()
  })

  test('renders statuses in Chinese', () => {
    render([task('a', '2026-09-20T19:56:33+00:00', 'completed')])

    expect(container.textContent).toContain('已完成')
    expect(container.textContent).not.toContain('completed')
  })

  test('selects a task by its id, not its label', () => {
    const selectTaskFromHistory = vi.fn()
    render([task('abc', '2026-09-20T19:56:33+00:00')], selectTaskFromHistory)

    act(() => {
      container.querySelector('button').click()
    })

    expect(selectTaskFromHistory).toHaveBeenCalledWith('abc')
  })
})
