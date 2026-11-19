import { describe, expect, test } from 'vitest'

import {
  backgroundTaskBadge,
  backgroundTaskProgress,
  classifyBackgroundTask,
  isBackgroundTaskActive,
  signinPlatformUrl,
  summarizeBatchResults,
} from './taskPresentation'

const withEndpoints = (endpoints) => ({ remoteEndpoints: { endpoints } })

describe('background task progress', () => {
  test('uses current as the processed count and keeps successes and failures apart', () => {
    expect(backgroundTaskProgress({ total: 4, current: 3, completed: 1, failed: 2, current_course: '高数' })).toEqual({
      total: 4, processed: 3, succeeded: 1, failed: 2, currentCourse: '高数',
    })
  })

  test('falls back to successes + failures for records without current', () => {
    expect(backgroundTaskProgress({ total: 5, completed: 2, failed: 1 })).toMatchObject({ processed: 3, succeeded: 2, failed: 1 })
    expect(backgroundTaskProgress({ total: 5, current: { token: 'x' }, completed: 1, failed: 0 })).toMatchObject({ processed: 1 })
  })

  test('never reports fewer processed than finished items or more than the total', () => {
    expect(backgroundTaskProgress({ total: 3, current: 1, completed: 2, failed: 1 })).toMatchObject({ processed: 3 })
    expect(backgroundTaskProgress({ total: 2, current: 9, completed: 0, failed: 0 })).toMatchObject({ processed: 2 })
    expect(backgroundTaskProgress(null)).toBe(null)
  })
})

describe('background task state', () => {
  test.each([
    [{ status: 'error', message: '签到未获确认，请在学习通核对签到状态。' }, 'unconfirmed', '签到结果未确认'],
    [{ status: 'error', message: '最终结果未保存。' }, 'unsaved', '最终结果未保存'],
    [{ status: 'running', message: 'Processed 1/3' }, 'running', '执行中'],
    [{ status: 'completed', message: 'Task completed' }, 'done', '已完成'],
    [{ status: 'completed', message: '此活动需要在学习通完成签到。' }, 'guided', '需在学习通完成'],
    [{ status: 'error', message: 'Task interrupted due to service restart' }, 'error', '未全部完成'],
    [{ status: 'cancelled' }, 'cancelled', '已取消'],
    [{ status: 'mystery' }, 'unknown', '状态未知'],
    [{}, 'unknown', '状态未知'],
    [null, 'unknown', '状态未知'],
  ])('classifies %j as %s', (task, state, label) => {
    expect(classifyBackgroundTask(task)).toBe(state)
    expect(backgroundTaskBadge(task).label).toBe(label)
  })

  test('an unconfirmed attempt wins over an unsaved result', () => {
    expect(classifyBackgroundTask({ status: 'error', message: '签到未获确认；最终结果未保存。' })).toBe('unconfirmed')
  })

  test('only a known running status counts as active', () => {
    expect(isBackgroundTaskActive({ status: 'running' })).toBe(true)
    expect(isBackgroundTaskActive({ status: 'pending' })).toBe(true)
    expect(isBackgroundTaskActive({ status: 'mystery' })).toBe(false)
    expect(isBackgroundTaskActive(null)).toBe(false)
  })
})

describe('学习通 navigation link', () => {
  const preSign = 'https://mobilelearn.chaoxing.com/newsign/preSign?courseId=1&classId=2&activePrimaryId=3'

  test('links only the official https confirmation page', () => {
    expect(signinPlatformUrl(withEndpoints({ preSign: { url: preSign } }))).toBe(preSign)
  })

  test.each([
    ['a submit endpoint', { submitSign: { url: 'https://mobilelearn.chaoxing.com/pptSign/stuSignajax?activeId=3' } }],
    ['a submit path in preSign', { preSign: { url: 'https://mobilelearn.chaoxing.com/pptSign/stuSignajax?activeId=3' } }],
    ['a non-official host', { preSign: { url: 'https://mobilelearn.chaoxing.com.example.com/newsign/preSign' } }],
    ['plain http', { preSign: { url: 'http://mobilelearn.chaoxing.com/newsign/preSign' } }],
    ['embedded credentials', { preSign: { url: 'https://user@mobilelearn.chaoxing.com/newsign/preSign' } }],
    ['javascript:', { preSign: { url: 'javascript:alert(1)' } }],
  ])('drops %s', (_, endpoints) => {
    expect(signinPlatformUrl(withEndpoints(endpoints))).toBe('')
  })
})

describe('batch result priority', () => {
  test('unconfirmed outranks 学习通 guidance, which outranks failure', () => {
    const results = [
      { status: true, message: '签到成功', name: 'A' },
      { status: false, message: '网络错误', name: 'B' },
      { status: false, message: '此活动需要在学习通完成签到。', name: 'C' },
      { status: false, message: '签到未获确认，请在学习通核对签到状态。', name: 'D' },
    ]
    const summary = summarizeBatchResults(results)
    expect(summary.kind).toBe('unconfirmed')
    expect(summary.lead.name).toBe('D')
    expect(summary.counts).toMatchObject({ done: 1, error: 1, guided: 1, unconfirmed: 1 })
    expect(summarizeBatchResults(results.slice(0, 3)).lead.name).toBe('C')
    expect(summarizeBatchResults(results.slice(0, 2)).lead.name).toBe('B')
    expect(summarizeBatchResults(results.slice(0, 1)).kind).toBe('done')
  })
})
