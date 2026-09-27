import { describe, expect, test } from 'vitest'

import { applyCourseProgressToTaskRecords, applyTaskActionToRecords, groupVideosByChapter } from './zhihuishuTasks'

describe('applyCourseProgressToTaskRecords', () => {
  test('updates only the active task when multiple tasks share one course', () => {
    const tasks = [
      {
        taskId: 'old-task',
        courseId: '1001',
        status: 'running',
        message: 'Old task still running',
        currentTask: 'Video 2',
        progress: { status: 'running', total: 3, completed: 1, percentage: 33.33 },
      },
      {
        taskId: 'active-task',
        courseId: '1001',
        status: 'running',
        message: 'Active task running',
        currentTask: 'Video 1',
        progress: { status: 'running', total: 2, completed: 1, percentage: 50 },
      },
    ]

    const updated = applyCourseProgressToTaskRecords(tasks, {
      courseId: '1001',
      activeTaskId: 'active-task',
      progress: {
        status: 'completed',
        message: 'Task completed',
        total: 2,
        completed: 2,
        failed: 0,
        percentage: 100,
        current_video: '',
      },
      updatedAt: '2026-03-31T00:00:00.000Z',
    })

    expect(updated[0].status).toBe('running')
    expect(updated[0].message).toBe('Old task still running')
    expect(updated[1].status).toBe('completed')
    expect(updated[1].message).toBe('Task completed')
    expect(updated[1].progress.completed).toBe(2)
  })

  test('does not overwrite task list when task id is unknown', () => {
    const tasks = [
      {
        taskId: 'task-a',
        courseId: '1001',
        status: 'running',
        message: 'Task A running',
        currentTask: 'Video 1',
        progress: { status: 'running', total: 2, completed: 1, percentage: 50 },
      },
    ]

    const updated = applyCourseProgressToTaskRecords(tasks, {
      courseId: '1001',
      activeTaskId: '',
      progress: {
        status: 'completed',
        message: 'Task completed',
        total: 2,
        completed: 2,
        failed: 0,
        percentage: 100,
        current_video: '',
      },
      updatedAt: '2026-03-31T00:00:00.000Z',
    })

    expect(updated).toEqual(tasks)
  })
})

describe('applyTaskActionToRecords', () => {
  const tasks = [
    { taskId: 'running', status: 'running', message: 'active' },
    { taskId: 'paused', status: 'paused', message: 'paused' },
    { taskId: 'completed', status: 'completed', message: 'done' },
    { taskId: 'failed', status: 'failed', message: 'failed' },
  ]

  test('never overwrites terminal history during global controls', () => {
    const cancelled = applyTaskActionToRecords(tasks, {
      action: 'cancel',
      message: 'cancelled',
      updatedAt: 'now',
    })

    expect(cancelled.find((task) => task.taskId === 'running').status).toBe('cancelled')
    expect(cancelled.find((task) => task.taskId === 'paused').status).toBe('cancelled')
    expect(cancelled.find((task) => task.taskId === 'completed')).toEqual(tasks[2])
    expect(cancelled.find((task) => task.taskId === 'failed')).toEqual(tasks[3])
  })

  test('applies pause and resume only to valid source states', () => {
    const paused = applyTaskActionToRecords(tasks, { action: 'pause' })
    expect(paused.find((task) => task.taskId === 'running').status).toBe('paused')
    expect(paused.find((task) => task.taskId === 'paused').status).toBe('paused')

    const resumed = applyTaskActionToRecords(tasks, { action: 'resume' })
    expect(resumed.find((task) => task.taskId === 'paused').status).toBe('running')
    expect(resumed.find((task) => task.taskId === 'running').status).toBe('running')
  })
})

describe('groupVideosByChapter', () => {
  test('groups videos into chapters in course order with counts', () => {
    const chapters = groupVideosByChapter([
      { id: 'v1', chapter_id: 'ch1', chapter_title: '第一章 绪论' },
      { id: 'v2', chapter_id: 'ch1', chapter_title: '第一章 绪论' },
      { id: 'v3', chapter_id: 'ch2', chapter_title: '' },
      { id: 'v4', chapter_id: 'ch3', chapter_title: '第三章 进阶' },
    ])

    expect(chapters).toEqual([
      { id: 'ch1', title: '第一章 绪论', videoCount: 2 },
      { id: 'ch2', title: '第 2 章', videoCount: 1 },
      { id: 'ch3', title: '第三章 进阶', videoCount: 1 },
    ])
  })

  test('skips videos without a chapter id and tolerates bad input', () => {
    expect(groupVideosByChapter([{ id: 'v1' }, { id: 'v2', chapter_id: 7 }])).toEqual([
      { id: '7', title: '第 1 章', videoCount: 1 },
    ])
    expect(groupVideosByChapter(null)).toEqual([])
  })
})
