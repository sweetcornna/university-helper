import { useCallback, useRef, useState } from 'react'
import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import useAutoSignin from './useAutoSignin'
import { CHAOXING_SETTINGS_KEY, DEFAULT_CHECK_INTERVAL_MINUTES } from '../utils'

const task = {
  taskId: 'task-1',
  courseId: 'course-1',
  courseName: '测试课程',
  type: 'normal',
}

const deferred = () => {
  let resolve
  let reject
  const promise = new Promise((promiseResolve, promiseReject) => {
    resolve = promiseResolve
    reject = promiseReject
  })
  return { promise, resolve, reject }
}

function AutoSigninHarness({ requestChaoxingApi, onExecute, executeBehavior, callbacks }) {
  const [form, setForm] = useState({ username: 'initial-user', password: 'initial-password' })
  const callbacksRef = useRef(
    callbacks || {
      setResultType: vi.fn(),
      setResultMessage: vi.fn(),
      setSigninTasks: vi.fn(),
      redirectingRef: { current: false },
    }
  )
  const executeSignin = useCallback(async (courseId, signType, options) => {
    const details = { username: form.username, password: form.password, courseId, signType, options }
    onExecute(details)
    return executeBehavior ? executeBehavior(details) : { status: true }
  }, [executeBehavior, form.password, form.username, onExecute])
  const autoSignin = useAutoSignin(form, executeSignin, requestChaoxingApi, callbacksRef.current)

  return (
    <>
      <input
        aria-label="username"
        value={form.username}
        onChange={(event) => setForm((previous) => ({ ...previous, username: event.target.value }))}
      />
      <input
        aria-label="password"
        value={form.password}
        onChange={(event) => setForm((previous) => ({ ...previous, password: event.target.value }))}
      />
      <button type="button" data-testid="toggle" onClick={() => autoSignin.setAutoSignin((previous) => !previous)}>
        toggle
      </button>
      <button type="button" data-testid="filter" onClick={() => autoSignin.setAutoSignFilter('photo')}>
        filter
      </button>
      <button type="button" data-testid="interval" onClick={() => autoSignin.setCheckInterval(1)}>
        interval
      </button>
      <output data-testid="auto-enabled">{String(autoSignin.autoSignin)}</output>
      <output data-testid="check-interval">{String(autoSignin.checkInterval)}</output>
    </>
  )
}

const flushPromises = async () => {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

const taskRequestCount = (requestChaoxingApi) =>
  requestChaoxingApi.mock.calls.filter(([path]) => path === '/tasks').length

describe('useAutoSignin scheduler dependencies', () => {
  beforeEach(() => {
    localStorage.removeItem(CHAOXING_SETTINGS_KEY)
    vi.useFakeTimers()
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  test('keeps the interval deadline stable while natural cycles use edited credentials', async () => {
    const requestChaoxingApi = vi.fn().mockResolvedValue({ data: [task] })
    const onExecute = vi.fn()
    const rendered = render(
      <AutoSigninHarness requestChaoxingApi={requestChaoxingApi} onExecute={onExecute} />
    )

    fireEvent.click(rendered.getByTestId('toggle'))
    await flushPromises()

    expect(taskRequestCount(requestChaoxingApi)).toBe(1)
    expect(onExecute).toHaveBeenCalledTimes(1)
    expect(onExecute.mock.calls[0][0]).toMatchObject({
      username: 'initial-user',
      password: 'initial-password',
    })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 1000)
    })
    await flushPromises()

    fireEvent.change(rendered.getByRole('textbox', { name: 'username' }), { target: { value: 'new-user' } })
    fireEvent.change(rendered.getByRole('textbox', { name: 'password' }), { target: { value: 'new-password' } })
    await flushPromises()

    expect(taskRequestCount(requestChaoxingApi)).toBe(1)
    expect(vi.getTimerCount()).toBe(2)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(DEFAULT_CHECK_INTERVAL_MINUTES * 60 * 1000 - 60 * 1000 - 1)
    })
    await flushPromises()
    expect(taskRequestCount(requestChaoxingApi)).toBe(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    await flushPromises()

    expect(taskRequestCount(requestChaoxingApi)).toBe(2)
    expect(onExecute).toHaveBeenCalledTimes(2)
    expect(onExecute.mock.calls[1][0]).toMatchObject({
      username: 'new-user',
      password: 'new-password',
    })
  })

  test('retains immediate restart semantics for filter, interval, and enable changes', async () => {
    const requestChaoxingApi = vi.fn().mockResolvedValue({ data: [task] })
    const onExecute = vi.fn()
    const rendered = render(
      <AutoSigninHarness requestChaoxingApi={requestChaoxingApi} onExecute={onExecute} />
    )

    fireEvent.click(rendered.getByTestId('toggle'))
    await flushPromises()
    expect(taskRequestCount(requestChaoxingApi)).toBe(1)

    fireEvent.click(rendered.getByTestId('filter'))
    await flushPromises()
    expect(taskRequestCount(requestChaoxingApi)).toBe(2)

    fireEvent.click(rendered.getByTestId('interval'))
    await flushPromises()
    expect(taskRequestCount(requestChaoxingApi)).toBe(3)
    expect(rendered.getByTestId('check-interval')).toHaveTextContent('1')

    fireEvent.click(rendered.getByTestId('toggle'))
    await flushPromises()
    expect(rendered.getByTestId('auto-enabled')).toHaveTextContent('false')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 1000)
    })
    await flushPromises()
    expect(taskRequestCount(requestChaoxingApi)).toBe(3)

    fireEvent.click(rendered.getByTestId('toggle'))
    await flushPromises()
    expect(taskRequestCount(requestChaoxingApi)).toBe(4)
  })

  test('does not execute tasks after disabling while the task list is pending', async () => {
    const taskRequest = deferred()
    const requestChaoxingApi = vi.fn(() => taskRequest.promise)
    const onExecute = vi.fn()
    const callbacks = {
      setResultType: vi.fn(),
      setResultMessage: vi.fn(),
      setSigninTasks: vi.fn(),
      redirectingRef: { current: false },
    }
    const rendered = render(
      <AutoSigninHarness
        callbacks={callbacks}
        requestChaoxingApi={requestChaoxingApi}
        onExecute={onExecute}
      />
    )

    fireEvent.click(rendered.getByTestId('toggle'))
    await flushPromises()
    expect(taskRequestCount(requestChaoxingApi)).toBe(1)

    fireEvent.click(rendered.getByTestId('toggle'))
    await flushPromises()

    await act(async () => {
      taskRequest.resolve({ data: [task] })
      await taskRequest.promise
    })
    await flushPromises()

    expect(onExecute).not.toHaveBeenCalled()
    expect(callbacks.setSigninTasks).not.toHaveBeenCalled()
    expect(callbacks.setResultType).not.toHaveBeenCalled()
  })

  test('stops the current cycle before starting its next task after disabling', async () => {
    const firstExecution = deferred()
    const requestChaoxingApi = vi.fn().mockResolvedValue({
      data: [
        task,
        { ...task, taskId: 'task-2', courseId: 'course-2', courseName: '第二门课程' },
      ],
    })
    const onExecute = vi.fn()
    const executeBehavior = vi.fn(() => firstExecution.promise)
    const callbacks = {
      setResultType: vi.fn(),
      setResultMessage: vi.fn(),
      setSigninTasks: vi.fn(),
      redirectingRef: { current: false },
    }
    const rendered = render(
      <AutoSigninHarness
        callbacks={callbacks}
        executeBehavior={executeBehavior}
        requestChaoxingApi={requestChaoxingApi}
        onExecute={onExecute}
      />
    )

    fireEvent.click(rendered.getByTestId('toggle'))
    await flushPromises()
    expect(onExecute).toHaveBeenCalledTimes(1)
    expect(onExecute).toHaveBeenCalledWith(expect.objectContaining({ courseId: 'course-1' }))

    fireEvent.click(rendered.getByTestId('toggle'))
    await flushPromises()

    await act(async () => {
      firstExecution.resolve({ status: true })
      await firstExecution.promise
    })
    await flushPromises()

    expect(onExecute).toHaveBeenCalledTimes(1)
    expect(executeBehavior).toHaveBeenCalledTimes(1)
    expect(callbacks.setResultType).not.toHaveBeenCalledWith('success')
    expect(callbacks.setResultMessage).not.toHaveBeenCalledWith(expect.stringContaining('自动签到完成'))
  })

  test('starts the new generation while the old task list is still pending', async () => {
    const oldTaskRequest = deferred()
    const newTaskRequest = deferred()
    const newExecution = deferred()
    const requestChaoxingApi = vi.fn()
      .mockReturnValueOnce(oldTaskRequest.promise)
      .mockReturnValueOnce(newTaskRequest.promise)
      .mockResolvedValue({ data: [] })
    const onExecute = vi.fn()
    const executeBehavior = vi.fn(() => newExecution.promise)
    const callbacks = {
      setResultType: vi.fn(),
      setResultMessage: vi.fn(),
      setSigninTasks: vi.fn(),
      redirectingRef: { current: false },
    }
    const rendered = render(
      <AutoSigninHarness
        callbacks={callbacks}
        executeBehavior={executeBehavior}
        requestChaoxingApi={requestChaoxingApi}
        onExecute={onExecute}
      />
    )

    fireEvent.click(rendered.getByTestId('interval'))
    await flushPromises()
    fireEvent.click(rendered.getByTestId('toggle'))
    await flushPromises()
    expect(taskRequestCount(requestChaoxingApi)).toBe(1)

    fireEvent.click(rendered.getByTestId('toggle'))
    await flushPromises()
    fireEvent.click(rendered.getByTestId('toggle'))
    await flushPromises()
    expect(taskRequestCount(requestChaoxingApi)).toBe(2)

    await act(async () => {
      newTaskRequest.resolve({ data: [task] })
      await newTaskRequest.promise
    })
    await flushPromises()
    expect(onExecute).toHaveBeenCalledTimes(1)

    await act(async () => {
      oldTaskRequest.resolve({ data: [task] })
      await oldTaskRequest.promise
    })
    await flushPromises()

    expect(callbacks.setSigninTasks).toHaveBeenCalledTimes(1)
    expect(callbacks.setResultType).not.toHaveBeenCalledWith('success')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 1000)
    })
    expect(taskRequestCount(requestChaoxingApi)).toBe(2)
    expect(onExecute).toHaveBeenCalledTimes(1)

    await act(async () => {
      newExecution.resolve({ status: true })
      await newExecution.promise
    })
    await flushPromises()

    expect(callbacks.setResultType).toHaveBeenCalledWith('success')
  })
})
