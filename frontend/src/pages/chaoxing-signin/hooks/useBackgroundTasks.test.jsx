import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import useBackgroundTasks from './useBackgroundTasks'
import { POLL_INTERVAL_MS } from '../utils'

const deferred = () => {
  let resolve
  let reject
  const promise = new Promise((promiseResolve, promiseReject) => {
    resolve = promiseResolve
    reject = promiseReject
  })
  return { promise, resolve, reject }
}

function BackgroundTasksHarness({ requestChaoxingApi, onReady }) {
  const backgroundTasks = useBackgroundTasks(requestChaoxingApi)
  onReady(backgroundTasks)
  return null
}

const renderBackgroundTasks = (requestChaoxingApi) => {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  let current

  act(() => {
    root.render(
      <BackgroundTasksHarness
        requestChaoxingApi={requestChaoxingApi}
        onReady={(backgroundTasks) => {
          current = backgroundTasks
        }}
      />
    )
  })

  return {
    get current() {
      return current
    },
    cleanup: () => {
      act(() => root.unmount())
      container.remove()
    },
  }
}

describe('useBackgroundTasks polling races', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  test('ignores a stale task rejection while the newer task remains in flight', async () => {
    const aStatus = deferred()
    const aLogs = deferred()
    const bStatus = deferred()
    const bLogs = deferred()
    const requestChaoxingApi = vi.fn((path) => {
      if (path === '/task/A') return aStatus.promise
      if (path === '/logs/A?cursor=0') return aLogs.promise
      if (path === '/task/B') return bStatus.promise
      if (path === '/logs/B?cursor=0') return bLogs.promise
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const setResultType = vi.fn()
    const setResultMessage = vi.fn()
    const callbacks = { setResultType, setResultMessage }
    const rendered = renderBackgroundTasks(requestChaoxingApi)
    let openAPromise
    let openBPromise

    try {
      await act(async () => {
        openAPromise = rendered.current.openBackgroundTask('A', callbacks)
      })
      await act(async () => {
        openBPromise = rendered.current.openBackgroundTask('B', callbacks)
      })

      expect(rendered.current.taskId).toBe('B')
      expect(rendered.current.statusLoading).toBe(true)
      expect(vi.getTimerCount()).toBe(1)

      await act(async () => {
        aStatus.reject(new Error('A failed'))
        aLogs.resolve({ data: [], cursor: 0 })
        await openAPromise
      })

      expect(setResultType).not.toHaveBeenCalled()
      expect(setResultMessage).not.toHaveBeenCalled()
      expect(rendered.current.statusLoading).toBe(true)
      expect(vi.getTimerCount()).toBe(1)

      await act(async () => {
        bStatus.resolve({ data: { status: 'completed', task_id: 'B' } })
        bLogs.resolve({ data: [{ message: 'B finished' }], cursor: 1 })
        await openBPromise
      })

      expect(rendered.current.taskStatus).toEqual({ status: 'completed', task_id: 'B' })
      expect(rendered.current.logs).toEqual([{ message: 'B finished' }])
      expect(rendered.current.statusLoading).toBe(false)
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      rendered.cleanup()
    }
  })

  test('starts a new generation when reopening the same task and ignores stale logs', async () => {
    const oldStatus = deferred()
    const oldLogs = deferred()
    const newStatus = deferred()
    const newLogs = deferred()
    const nextStatus = deferred()
    const nextLogs = deferred()
    const statusResponses = [oldStatus, newStatus, nextStatus]
    const logResponses = [oldLogs, newLogs, nextLogs]
    let statusCalls = 0
    let logsCalls = 0
    const requestChaoxingApi = vi.fn((path) => {
      if (path === '/task/X') return statusResponses[statusCalls++].promise
      if (path.startsWith('/logs/X?cursor=')) return logResponses[logsCalls++].promise
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const rendered = renderBackgroundTasks(requestChaoxingApi)
    let oldOpenPromise
    let newOpenPromise

    try {
      await act(async () => {
        oldOpenPromise = rendered.current.openBackgroundTask('X')
      })

      await act(async () => {
        oldStatus.resolve({ data: { status: 'running', task_id: 'X' } })
        await Promise.resolve()
        await Promise.resolve()
      })
      expect(rendered.current.taskStatus).toEqual({ status: 'running', task_id: 'X' })
      expect(rendered.current.statusLoading).toBe(true)

      await act(async () => {
        newOpenPromise = rendered.current.openBackgroundTask('X')
      })

      expect(statusCalls).toBe(2)
      expect(logsCalls).toBe(2)
      expect(requestChaoxingApi).toHaveBeenNthCalledWith(4, '/logs/X?cursor=0')
      expect(rendered.current.taskStatus).toBe(null)
      expect(rendered.current.logs).toEqual([])
      expect(rendered.current.statusLoading).toBe(true)
      expect(vi.getTimerCount()).toBe(1)

      await act(async () => {
        newStatus.resolve({ data: { status: 'running', task_id: 'X' } })
        newLogs.resolve({ data: [{ message: 'new generation' }], cursor: 101 })
        await newOpenPromise
      })

      expect(rendered.current.taskStatus).toEqual({ status: 'running', task_id: 'X' })
      expect(rendered.current.logs).toEqual([{ message: 'new generation' }])
      expect(rendered.current.statusLoading).toBe(false)
      expect(vi.getTimerCount()).toBe(1)

      await act(async () => {
        oldLogs.resolve({ data: [{ message: 'stale generation' }], cursor: 999 })
        await oldOpenPromise
      })

      expect(rendered.current.taskStatus).toEqual({ status: 'running', task_id: 'X' })
      expect(rendered.current.logs).toEqual([{ message: 'new generation' }])
      expect(rendered.current.statusLoading).toBe(false)
      expect(vi.getTimerCount()).toBe(1)

      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
      })
      expect(requestChaoxingApi).toHaveBeenLastCalledWith('/logs/X?cursor=101')

      await act(async () => {
        nextStatus.resolve({ data: { status: 'completed', task_id: 'X' } })
        nextLogs.resolve({ data: [], cursor: 101 })
        await Promise.resolve()
        await Promise.resolve()
      })
      expect(rendered.current.statusLoading).toBe(false)
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      rendered.cleanup()
    }
  })

  test('external task clearing invalidates a pending generation', async () => {
    const status = deferred()
    const logs = deferred()
    const requestChaoxingApi = vi.fn((path) => {
      if (path === '/task/X') return status.promise
      if (path === '/logs/X?cursor=0') return logs.promise
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const rendered = renderBackgroundTasks(requestChaoxingApi)
    let openPromise

    try {
      await act(async () => {
        openPromise = rendered.current.openBackgroundTask('X')
      })
      expect(rendered.current.statusLoading).toBe(true)
      expect(vi.getTimerCount()).toBe(1)

      await act(async () => {
        rendered.current.setTaskId('')
      })
      expect(rendered.current.taskId).toBe('')
      expect(rendered.current.statusLoading).toBe(false)
      expect(vi.getTimerCount()).toBe(0)

      await act(async () => {
        status.resolve({ data: { status: 'completed', task_id: 'X' } })
        logs.resolve({ data: [{ message: 'stale after clear' }], cursor: 1 })
        await openPromise
      })

      expect(rendered.current.taskStatus).toBe(null)
      expect(rendered.current.logs).toEqual([])
      expect(rendered.current.statusLoading).toBe(false)
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      rendered.cleanup()
    }
  })

  test('reports and stops polling when the current task fails', async () => {
    const status = deferred()
    const logs = deferred()
    const requestChaoxingApi = vi.fn((path) => {
      if (path === '/task/current') return status.promise
      if (path === '/logs/current?cursor=0') return logs.promise
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const setResultType = vi.fn()
    const setResultMessage = vi.fn()
    const rendered = renderBackgroundTasks(requestChaoxingApi)
    let openPromise

    try {
      await act(async () => {
        openPromise = rendered.current.openBackgroundTask('current', {
          setResultType,
          setResultMessage,
        })
      })
      expect(rendered.current.statusLoading).toBe(true)
      expect(vi.getTimerCount()).toBe(1)

      await act(async () => {
        status.reject(new Error('current task failed'))
        await openPromise
      })

      expect(setResultType).toHaveBeenCalledWith('error')
      expect(setResultMessage).toHaveBeenCalledWith('current task failed')
      expect(rendered.current.statusLoading).toBe(false)
      expect(vi.getTimerCount()).toBe(0)

      // The status failure must finish without waiting for logs. Rejecting the
      // still-pending logs request afterwards must remain handled.
      await act(async () => {
        logs.reject(new Error('logs also failed'))
        await Promise.resolve()
        await Promise.resolve()
      })
    } finally {
      rendered.cleanup()
    }
  })

  test('keeps status and polling alive when logs fail', async () => {
    const firstStatus = deferred()
    const firstLogs = deferred()
    const secondStatus = deferred()
    const secondLogs = deferred()
    let statusCalls = 0
    let logsCalls = 0
    const requestChaoxingApi = vi.fn((path) => {
      if (path === '/task/current') {
        statusCalls += 1
        return (statusCalls === 1 ? firstStatus : secondStatus).promise
      }
      if (path === '/logs/current?cursor=0') {
        logsCalls += 1
        return (logsCalls === 1 ? firstLogs : secondLogs).promise
      }
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const logError = vi.spyOn(console, 'error').mockImplementation(() => {})
    const rendered = renderBackgroundTasks(requestChaoxingApi)
    let openPromise

    try {
      await act(async () => {
        openPromise = rendered.current.openBackgroundTask('current')
      })

      expect(statusCalls).toBe(1)
      expect(logsCalls).toBe(1)
      expect(rendered.current.statusLoading).toBe(true)
      expect(vi.getTimerCount()).toBe(1)

      await act(async () => {
        firstStatus.resolve({ data: { status: 'running', task_id: 'current' } })
        firstLogs.reject(new Error('logs unavailable'))
        await openPromise
      })

      expect(rendered.current.taskStatus).toEqual({ status: 'running', task_id: 'current' })
      expect(rendered.current.statusLoading).toBe(false)
      expect(logError).toHaveBeenCalledWith(
        'Failed to fetch background task logs for current:',
        expect.any(Error)
      )
      expect(vi.getTimerCount()).toBe(1)

      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
      })

      expect(statusCalls).toBe(2)
      expect(logsCalls).toBe(2)
      expect(rendered.current.statusLoading).toBe(true)

      await act(async () => {
        secondStatus.resolve({ data: { status: 'completed', task_id: 'current' } })
        secondLogs.resolve({ data: [{ message: 'finished' }], cursor: 1 })
        await Promise.resolve()
        await Promise.resolve()
      })

      expect(rendered.current.taskStatus).toEqual({ status: 'completed', task_id: 'current' })
      expect(rendered.current.logs).toEqual([{ message: 'finished' }])
      expect(rendered.current.statusLoading).toBe(false)
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      rendered.cleanup()
    }
  })
})
