import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import useBackgroundTasks from './useBackgroundTasks'

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
        logs.resolve({ data: [], cursor: 0 })
        await openPromise
      })

      expect(setResultType).toHaveBeenCalledWith('error')
      expect(setResultMessage).toHaveBeenCalledWith('current task failed')
      expect(rendered.current.statusLoading).toBe(false)
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      rendered.cleanup()
    }
  })
})
