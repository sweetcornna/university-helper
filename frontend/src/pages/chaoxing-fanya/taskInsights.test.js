import { describe, expect, test } from 'vitest'

import { translateCurrentTask, translateTaskMessage } from '../../utils/taskMessages'
import { taskStatusLabel } from '../../utils/taskStatus'
import { collectIssues, describeLoadError, describeStartError, describeTask, parseChapterLog } from './taskInsights'

const log = (level, message) => ({ timestamp: '2026-10-22T09:00:00+08:00', level, message })

describe('status labels', () => {
  test.each([
    ['pending', '等待开始'],
    ['running', '进行中'],
    ['paused', '已暂停'],
    ['cancelling', '正在停止'],
    ['completed', '已完成'],
    ['failed', '失败'],
    ['error', '出错'],
    ['cancelled', '已取消'],
    ['RUNNING', '进行中'],
  ])('%s -> %s', (status, label) => {
    expect(taskStatusLabel(status)).toBe(label)
  })

  test('unknown or empty status never leaks raw English', () => {
    expect(taskStatusLabel('weird')).toBe('状态未知')
    expect(taskStatusLabel('')).toBe('状态未知')
  })
})

describe('translateTaskMessage', () => {
  test.each([
    ['Starting login...', '开始登录学习通…'],
    ['Login successful', '学习通登录成功'],
    ['Login failed', '学习通登录失败'],
    ['Start course: 示例课程', '开始学习课程：示例课程'],
    ['Course finished with 2 failed chapters: 示例课程', '课程结束，有 2 个章节没有完成：示例课程'],
    ['Task finished with failures (1 failed courses)', '任务结束，1 门课程没有全部完成'],
    ['Task completed', '任务完成'],
    ['Task cancelled by user', '任务已按你的要求停止'],
    ['Task interrupted due to service restart', '服务重启，任务被中断'],
    ['Fetch chapters failed for 示例课程: timeout', '获取「示例课程」的章节失败（timeout）'],
    ['Selected 2 courses, speed 1.5x, jobs 4', '已选 2 门课程，1.5 倍速，4 个并发章节'],
    ['Failed to load Zhihuishu videos', '读取智慧树视频列表失败'],
  ])('%s', (input, expected) => {
    expect(translateTaskMessage(input)).toBe(expected)
  })

  test('Chinese and unknown text pass through unchanged', () => {
    expect(translateTaskMessage('章节「1.1」处理失败')).toBe('章节「1.1」处理失败')
    expect(translateTaskMessage('Something new')).toBe('Something new')
  })

  test('current_task machine values are readable', () => {
    expect(translateCurrentTask('chapter:2.1 听力')).toBe('章节：2.1 听力')
    expect(translateCurrentTask('finished')).toBe('已结束')
  })
})

describe('parseChapterLog', () => {
  test('reads the retrying line', () => {
    expect(parseChapterLog('章节「3.2 测验」处理失败，正在自动重试（最多 5 次）。原因：题库没有答案')).toEqual({
      kind: 'retrying', chapter: '3.2 测验', tries: 5, reason: '题库没有答案',
    })
  })

  test('reads the skipped line with its hint', () => {
    expect(parseChapterLog('章节「3.2 测验」重试 5 次仍失败，已跳过。原因：题库没有答案。建议：换一个题库')).toEqual({
      kind: 'skipped', chapter: '3.2 测验', tries: 5, reason: '题库没有答案', hint: '换一个题库',
    })
  })
})

describe('collectIssues', () => {
  test('prefers structured failures and drops duplicated chapter lines', () => {
    const { issues } = collectIssues(
      { failures: [{ course: 'A', chapter: '1.1', reason: '没找到答案', hint: '换题库', timestamp: 't' }] },
      [
        log('info', 'Start course: A'),
        log('error', '章节「1.1」重试 5 次仍失败，已跳过。原因：没找到答案。建议：换题库'),
        log('warning', 'Course finished with 1 failed chapters: A'),
      ],
    )
    expect(issues).toHaveLength(1)
    expect(issues[0]).toMatchObject({ course: 'A', chapter: '1.1', reason: '没找到答案', hint: '换题库' })
  })

  test('falls back to log lines on the current backend', () => {
    const { issues } = collectIssues({ status: 'failed' }, [
      log('info', 'Start course: A'),
      log('warning', 'Course finished with 2 failed chapters: A'),
      log('warning', 'Task finished with failures'),
    ])
    expect(issues).toHaveLength(1)
    expect(issues[0]).toMatchObject({ course: 'A', reason: '有 2 个章节没有完成' })
  })

  test('a skipped chapter is no longer counted as retrying', () => {
    const { retrying, issues } = collectIssues({}, [
      log('info', 'Start course: A'),
      log('warning', '章节「1.1」处理失败，正在自动重试（最多 5 次）。原因：x'),
      log('warning', '章节「1.2」处理失败，正在自动重试（最多 5 次）。原因：y'),
      log('error', '章节「1.1」重试 5 次仍失败，已跳过。原因：x'),
    ])
    expect(retrying.map((item) => item.chapter)).toEqual(['1.2'])
    expect(issues.map((item) => item.chapter)).toEqual(['1.1'])
  })
})

describe('describeTask', () => {
  test('no task reads as not started', () => {
    expect(describeTask(null).headline).toBe('还没有开始任务')
  })

  test('running task leads with the current course', () => {
    const view = describeTask({ status: 'running', progress: { current_course: '大学英语', current_chapter: '2.1' } })
    expect(view.label).toBe('进行中')
    expect(view.headline).toBe('正在学习「大学英语」')
    expect(view.detail).toBe('当前章节：2.1')
    expect(view.attention).toBeNull()
  })

  test('retrying chapters raise a warning while running', () => {
    const view = describeTask({ status: 'running', progress: {} }, [log('warning', '章节「1.1」处理失败，正在自动重试（最多 5 次）。原因：x')])
    expect(view.attention).toMatchObject({ tone: 'warning', title: '1 个章节正在自动重试' })
  })

  test('partial failure explains what was not done and offers next steps', () => {
    const view = describeTask(
      { status: 'failed', message: 'Task finished with failures (1 failed courses)', progress: { total: 2, completed: 1, failed: 1 }, failures: [{ course: 'B', chapter: '3.2', reason: '题库没有答案', hint: '换一个题库' }] },
      [],
    )
    expect(view.headline).toBe('1 门课程没有全部完成')
    expect(view.attention.issues[0]).toMatchObject({ chapter: '3.2', hint: '换一个题库' })
    expect(view.attention.actions).toEqual(['settings', 'retry'])
  })

  test('login failure points to re-login', () => {
    const view = describeTask({ status: 'failed', message: 'Login failed', progress: {} }, [log('error', 'Login failed')])
    expect(view.headline).toBe('学习通登录失败')
    expect(view.attention.actions).toContain('relogin')
  })

  test('service restart is explained in Chinese', () => {
    const view = describeTask({ status: 'failed', message: 'Task interrupted due to service restart', progress: {} })
    expect(view.headline).toBe('服务重启，任务被中断')
    expect(view.attention.summary).toContain('服务重启')
  })

  test('cancelled task has no failure panel', () => {
    expect(describeTask({ status: 'cancelled', progress: {} }, [log('warning', 'Task cancelled by user')]).attention).toBeNull()
  })
})

describe('describeStartError', () => {
  test('422 endpoint error points to 学习配置', () => {
    const view = describeStartError({ status: 422, message: 'Invalid answer-provider endpoint configuration' })
    expect(view.title).toBe('题库设置需要调整')
    expect(view.actions).toEqual(['settings'])
  })

  test('409 means a task is already running', () => {
    expect(describeStartError({ status: 409, message: 'An active task already exists for this user' })).toMatchObject({ actions: ['tasks'] })
  })

  test('third-party 401 asks to log in to 学习通 again', () => {
    const view = describeStartError({ status: 401, message: '学习通登录已失效，请在平台账号中重新登录学习通。' })
    expect(view.title).toBe('学习通登录已失效')
    expect(view.actions).toEqual(['relogin'])
  })

  test('plain errors keep their message', () => {
    expect(describeStartError(new Error('network failure')).detail).toBe('network failure')
  })
})

describe('describeLoadError', () => {
  test('flags re-login for an expired platform session', () => {
    expect(describeLoadError({ status: 401, message: 'Please login to Chaoxing first' }, '课程列表')).toEqual({
      title: '课程列表没有加载出来', detail: '请先登录学习通', relogin: true,
    })
  })
})
