import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'

import BackgroundTaskDetail from './BackgroundTaskDetail'

const renderDetail = (taskStatus, logs = []) => render(
  <BackgroundTaskDetail taskId="task-1" taskStatus={taskStatus} logs={logs} statusLoading={false} onRefresh={() => {}} />
)

afterEach(cleanup)

describe('BackgroundTaskDetail', () => {
  test('shows processed/total from current with successes and failures apart', () => {
    renderDetail({ status: 'running', progress: { total: 4, current: 3, completed: 1, failed: 2, current_course: '高数' } })
    expect(screen.getByText('已处理 3/4')).toBeInTheDocument()
    expect(screen.getByText('成功 1 项 · 失败 2 项 · 当前：高数')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: '已处理 3/4' })).toHaveAttribute('aria-valuenow', '75')
  })

  test('older records without current count successes + failures as processed', () => {
    renderDetail({ status: 'error', message: 'Task completed with failures', progress: { total: 3, completed: 1, failed: 1 } })
    expect(screen.getByText('已处理 2/3')).toBeInTheDocument()
    expect(screen.getByText('成功 1 项 · 失败 1 项')).toBeInTheDocument()
    expect(screen.getAllByText('未全部完成').length).toBeGreaterThan(0)
  })

  test('separates an unsaved final result from an unconfirmed sign-in', () => {
    renderDetail({ status: 'error', message: '最终结果未保存。' })
    expect(screen.getAllByText('最终结果未保存').length).toBe(2)
    expect(screen.queryByText('签到结果未确认')).not.toBeInTheDocument()
    cleanup()

    renderDetail({ status: 'error', message: '签到未获确认，请在学习通核对签到状态。' })
    expect(screen.getAllByText('签到结果未确认').length).toBe(2)
    expect(screen.queryByText('最终结果未保存')).not.toBeInTheDocument()
    expect(screen.getByText(/不要重复提交/)).toBeInTheDocument()
  })

  test('an unrecognised status is shown as unknown, never as running', () => {
    renderDetail({ status: 'mystery' })
    expect(screen.getAllByText('状态未知').length).toBe(2)
    expect(screen.queryByText('执行中')).not.toBeInTheDocument()
  })

  test('a completed run that hands off to 学习通 is not shown as a success', () => {
    renderDetail({ status: 'completed', message: '此活动需要在学习通完成签到。' })
    expect(screen.getAllByText('需在学习通完成').length).toBe(2)
    expect(screen.queryByText('已完成')).not.toBeInTheDocument()
  })
})
