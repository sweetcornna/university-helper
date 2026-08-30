import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'

import TaskControlSection from './TaskControlSection'


const renderControls = (controlLoading = {}) => render(
  <TaskControlSection
    taskId="task-A"
    taskStatus={{ status: 'running' }}
    loading={false}
    isRunning
    statusText="running"
    startTask={vi.fn()}
    controlTask={vi.fn()}
    controlLoading={controlLoading}
  />
)


describe('TaskControlSection control loading', () => {
  afterEach(() => {
    cleanup()
  })


  test('disables only the in-flight action while preserving existing status gates', () => {
    renderControls({ pause: true })


    expect(screen.getByRole('button', { name: '暂停' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '继续' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '停止' })).toBeEnabled()
  })
})
