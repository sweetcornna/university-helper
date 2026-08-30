import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import useTaskExecution from './useTaskExecution'


const deferred = () => {
  let resolve
  let reject
  const promise = new Promise((promiseResolve, promiseReject) => {
    resolve = promiseResolve
    reject = promiseReject
  })
  return { promise, resolve, reject }
}


const flush = async () => {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}


function TaskExecutionHarness({ callApi, setError, setNotice, pollRef, stopPolling, onReady }) {
  const taskExecution = useTaskExecution({ callApi, setError, setNotice, pollRef, stopPolling })
  onReady(taskExecution)
  return null
}


const renderTaskExecution = (callApi) => {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const pollRef = { current: null }
  const setError = vi.fn()
  const setNotice = vi.fn()
  const stopPolling = vi.fn(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  })
  let current


  act(() => {
    root.render(
      <TaskExecutionHarness
        callApi={callApi}
        setError={setError}
        setNotice={setNotice}
        pollRef={pollRef}
        stopPolling={stopPolling}
        onReady={(taskExecution) => {
          current = taskExecution
        }}
      />
    )
  })


  return {
    get current() {
      return current
    },
    setError,
    setNotice,
    stopPolling,
    cleanup: () => {
      act(() => root.unmount())
      container.remove()
    },
  }
}


const status = (taskId, value = 'running') => ({
  task_id: taskId,
  status: value,
  updated_at: `${taskId}-${value}`,
})


const logs = (message, cursor = 1) => ({
  data: [{ timestamp: message, level: 'info', message }],
  cursor,
})


describe('useTaskExecution task generations', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })


  afterEach(() => {
    vi.useRealTimers()
  })


  test('ignores a stale success from A after switching to B', async () => {
    const aStatus = deferred()
    const aLogs = deferred()
    const callApi = vi.fn((path) => {
      if (path === '/course/tasks') return Promise.resolve([])
      if (path === '/course/status/A') return aStatus.promise
      if (path === '/course/logs/A?cursor=0') return aLogs.promise
      if (path === '/course/status/B') return Promise.resolve(status('B'))
      if (path === '/course/logs/B?cursor=0') return Promise.resolve(logs('B'))
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const rendered = renderTaskExecution(callApi)


    try {
      act(() => rendered.current.setTaskId('A'))
      expect(callApi).toHaveBeenCalledWith('/course/status/A')


      await act(async () => {
        aStatus.resolve(status('A'))
        await Promise.resolve()
        await Promise.resolve()
      })
      expect(callApi).toHaveBeenCalledWith('/course/logs/A?cursor=0')


      act(() => rendered.current.setTaskId('B'))
      await flush()


      expect(rendered.current.taskId).toBe('B')
      expect(callApi.mock.calls.filter(([path]) => path === '/course/status/B')).toHaveLength(1)
      expect(callApi.mock.calls.filter(([path]) => path === '/course/logs/B?cursor=0')).toHaveLength(1)


      await act(async () => {
        aLogs.resolve(logs('A'))
        await Promise.resolve()
        await Promise.resolve()
      })
      await flush()


      expect(rendered.current.taskStatus.task_id).toBe('B')
      expect(rendered.current.logs.map((item) => item.message)).toEqual(['B'])
      expect(rendered.setError).not.toHaveBeenCalled()
    } finally {
      rendered.cleanup()
    }
  })


  test('ignores a stale failure from A after switching to B', async () => {
    const aStatus = deferred()
    const aLogs = deferred()
    const callApi = vi.fn((path) => {
      if (path === '/course/tasks') return Promise.resolve([])
      if (path === '/course/status/A') return aStatus.promise
      if (path === '/course/logs/A?cursor=0') return aLogs.promise
      if (path === '/course/status/B') return Promise.resolve(status('B'))
      if (path === '/course/logs/B?cursor=0') return Promise.resolve(logs('B'))
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const rendered = renderTaskExecution(callApi)


    try {
      act(() => rendered.current.setTaskId('A'))
      await act(async () => {
        aStatus.resolve(status('A'))
        await Promise.resolve()
        await Promise.resolve()
      })
      expect(callApi).toHaveBeenCalledWith('/course/logs/A?cursor=0')


      act(() => rendered.current.setTaskId('B'))
      await flush()


      await act(async () => {
        aLogs.reject(new Error('A failed'))
        await Promise.resolve()
        await Promise.resolve()
      })
      await flush()


      expect(rendered.current.taskStatus.task_id).toBe('B')
      expect(rendered.current.logs.map((item) => item.message)).toEqual(['B'])
      expect(rendered.setError).not.toHaveBeenCalled()
    } finally {
      rendered.cleanup()
    }
  })


  test('clears A status immediately and shows only B after its delayed snapshot succeeds', async () => {
    const bStatus = deferred()
    const callApi = vi.fn((path) => {
      if (path === '/course/tasks') return Promise.resolve([])
      if (path === '/course/status/A') return Promise.resolve(status('A'))
      if (path === '/course/logs/A?cursor=0') return Promise.resolve(logs('A'))
      if (path === '/course/status/B') return bStatus.promise
      if (path === '/course/logs/B?cursor=0') return Promise.resolve(logs('B'))
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const rendered = renderTaskExecution(callApi)


    try {
      act(() => rendered.current.setTaskId('A'))
      await flush()
      expect(rendered.current.taskStatus.task_id).toBe('A')


      act(() => rendered.current.selectTaskFromHistory('B'))
      expect(rendered.current.taskId).toBe('B')
      expect(rendered.current.taskStatus).toBeNull()
      expect(callApi.mock.calls.filter(([path]) => path === '/course/status/B')).toHaveLength(1)


      await act(async () => {
        bStatus.resolve(status('B'))
        await Promise.resolve()
        await Promise.resolve()
      })
      await flush()


      expect(rendered.current.taskStatus.task_id).toBe('B')
      expect(rendered.current.logs.map((item) => item.message)).toEqual(['B'])
    } finally {
      rendered.cleanup()
    }
  })


  test('does not retain A status when the selected B snapshot fails', async () => {
    const bStatus = deferred()
    const callApi = vi.fn((path) => {
      if (path === '/course/tasks') return Promise.resolve([])
      if (path === '/course/status/A') return Promise.resolve(status('A'))
      if (path === '/course/logs/A?cursor=0') return Promise.resolve(logs('A'))
      if (path === '/course/status/B') return bStatus.promise
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const rendered = renderTaskExecution(callApi)


    try {
      act(() => rendered.current.setTaskId('A'))
      await flush()
      expect(rendered.current.taskStatus.task_id).toBe('A')


      act(() => rendered.current.selectTaskFromHistory('B'))
      expect(rendered.current.taskStatus).toBeNull()


      await act(async () => {
        bStatus.reject(new Error('B failed'))
        await Promise.resolve()
        await Promise.resolve()
      })
      await flush()


      expect(rendered.current.taskStatus).toBeNull()
      expect(rendered.setError).toHaveBeenCalledWith('B failed')
    } finally {
      rendered.cleanup()
    }
  })


  test('restoring a task uses the taskId effect as its only initial load', async () => {
    const callApi = vi.fn((path) => {
      if (path === '/course/tasks') return Promise.resolve({ tasks: [status('B')] })
      if (path === '/course/status/B') return Promise.resolve(status('B'))
      if (path.startsWith('/course/logs/B?cursor=')) return Promise.resolve(logs('B'))
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const rendered = renderTaskExecution(callApi)


    try {
      await flush()
      expect(rendered.current.taskId).toBe('B')
      expect(rendered.current.taskHistory.map((item) => item.task_id)).toEqual(['B'])
      expect(callApi.mock.calls.filter(([path]) => path === '/course/status/B')).toHaveLength(1)
      expect(callApi.mock.calls.filter(([path]) => path.startsWith('/course/logs/B?cursor=')).length).toBe(1)
    } finally {
      rendered.cleanup()
    }
  })


  test('changing to a history task uses the taskId effect as its only initial load', async () => {
    const callApi = vi.fn((path) => {
      if (path === '/course/tasks') return Promise.resolve([])
      if (path === '/course/status/A') return Promise.resolve(status('A'))
      if (path === '/course/logs/A?cursor=0') return Promise.resolve(logs('A'))
      if (path === '/course/status/B') return Promise.resolve(status('B'))
      if (path === '/course/logs/B?cursor=0') return Promise.resolve(logs('B'))
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const rendered = renderTaskExecution(callApi)


    try {
      await flush()
      act(() => rendered.current.setTaskId('A'))
      await flush()
      expect(vi.getTimerCount()).toBe(1)
      act(() => rendered.current.selectTaskFromHistory('B'))
      await flush()


      expect(rendered.current.taskId).toBe('B')
      expect(callApi.mock.calls.filter(([path]) => path === '/course/status/A')).toHaveLength(1)
      expect(callApi.mock.calls.filter(([path]) => path === '/course/logs/A?cursor=0')).toHaveLength(1)
      expect(callApi.mock.calls.filter(([path]) => path === '/course/status/B')).toHaveLength(1)
      expect(callApi.mock.calls.filter(([path]) => path === '/course/logs/B?cursor=0')).toHaveLength(1)
      expect(vi.getTimerCount()).toBe(1)
    } finally {
      rendered.cleanup()
    }
  })


  test('reselecting the current task refreshes once with a reset cursor', async () => {
    const refreshedLogs = deferred()
    let statusCalls = 0
    let logsCalls = 0
    const callApi = vi.fn((path) => {
      if (path === '/course/tasks') return Promise.resolve([])
      if (path === '/course/status/B') {
        statusCalls += 1
        return Promise.resolve(status('B'))
      }
      if (path.startsWith('/course/logs/B?cursor=')) {
        logsCalls += 1
        return logsCalls === 1 ? Promise.resolve(logs('initial', 7)) : refreshedLogs.promise
      }
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const rendered = renderTaskExecution(callApi)


    try {
      act(() => rendered.current.setTaskId('B'))
      await flush()
      expect(statusCalls).toBe(1)
      expect(logsCalls).toBe(1)
      expect(rendered.current.logCursor).toBe(7)
      expect(vi.getTimerCount()).toBe(1)


      act(() => rendered.current.selectTaskFromHistory('B'))
      await flush()
      expect(statusCalls).toBe(2)
      expect(logsCalls).toBe(2)
      expect(rendered.current.logCursor).toBe(0)
      expect(vi.getTimerCount()).toBe(1)


      act(() => rendered.current.selectTaskFromHistory('B'))
      await flush()
      expect(statusCalls).toBe(2)
      expect(logsCalls).toBe(2)


      await act(async () => {
        refreshedLogs.resolve(logs('refreshed', 9))
        await Promise.resolve()
        await Promise.resolve()
      })
      await flush()


      expect(rendered.current.logCursor).toBe(9)
      expect(rendered.current.logs.map((item) => item.message)).toEqual(['refreshed'])
      expect(vi.getTimerCount()).toBe(1)


      act(() => {
        vi.advanceTimersByTime(2500)
      })
      await flush()
      expect(statusCalls).toBe(3)
      expect(logsCalls).toBe(3)
      expect(vi.getTimerCount()).toBe(1)
    } finally {
      rendered.cleanup()
    }
  })


  test('does not overlap polling requests and stops after B reaches a terminal state', async () => {
    const bStatusFirst = deferred()
    const bLogsFirst = deferred()
    const bStatusSecond = deferred()
    const bLogsSecond = deferred()
    let statusCalls = 0
    let logsCalls = 0
    const callApi = vi.fn((path) => {
      if (path === '/course/tasks') return Promise.resolve([])
      if (path === '/course/status/B') {
        statusCalls += 1
        return (statusCalls === 1 ? bStatusFirst : bStatusSecond).promise
      }
      if (path.startsWith('/course/logs/B?cursor=')) {
        logsCalls += 1
        return (logsCalls === 1 ? bLogsFirst : bLogsSecond).promise
      }
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const rendered = renderTaskExecution(callApi)


    try {
      act(() => rendered.current.setTaskId('B'))
      expect(statusCalls).toBe(1)
      expect(vi.getTimerCount()).toBe(1)


      await act(async () => {
        bStatusFirst.resolve(status('B'))
        await Promise.resolve()
        await Promise.resolve()
      })
      expect(logsCalls).toBe(1)


      act(() => {
        vi.advanceTimersByTime(2500)
      })
      expect(statusCalls).toBe(1)


      await act(async () => {
        bLogsFirst.resolve(logs('B first'))
        await Promise.resolve()
        await Promise.resolve()
      })
      act(() => {
        vi.advanceTimersByTime(2500)
      })
      expect(statusCalls).toBe(2)


      await act(async () => {
        bStatusSecond.resolve(status('B', 'completed'))
        await Promise.resolve()
        await Promise.resolve()
      })
      expect(logsCalls).toBe(2)


      await act(async () => {
        bLogsSecond.resolve(logs('B done', 2))
        await Promise.resolve()
        await Promise.resolve()
      })
      await flush()


      expect(rendered.current.taskStatus.status).toBe('completed')
      expect(rendered.current.logs.map((item) => item.message)).toEqual(['B first', 'B done'])
      expect(rendered.stopPolling).toHaveBeenCalled()
      expect(vi.getTimerCount()).toBe(0)


      act(() => rendered.current.selectTaskFromHistory('B'))
      await flush()
      expect(statusCalls).toBe(3)
      expect(logsCalls).toBe(3)
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      rendered.cleanup()
    }
  })


  test('deduplicates a control action while pending and allows the state-gated next action after success', async () => {
    const pauseRequest = deferred()
    let statusCalls = 0
    const callApi = vi.fn((path) => {
      if (path === '/course/tasks') return Promise.resolve([])
      if (path === '/course/status/A') {
        statusCalls += 1
        return Promise.resolve(status('A', statusCalls === 1 ? 'running' : 'paused'))
      }
      if (path.startsWith('/course/logs/A?cursor=')) return Promise.resolve(logs('A', statusCalls))
      if (path === '/course/task/A/pause') return pauseRequest.promise
      if (path === '/course/task/A/resume') return Promise.resolve({ message: 'Task resumed' })
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const rendered = renderTaskExecution(callApi)


    try {
      act(() => rendered.current.setTaskId('A'))
      await flush()


      let firstPause
      let secondPause
      act(() => {
        firstPause = rendered.current.controlTask('pause')
        secondPause = rendered.current.controlTask('pause')
      })
      expect(callApi.mock.calls.filter(([path]) => path === '/course/task/A/pause')).toHaveLength(1)
      expect(rendered.current.controlLoading).toEqual({ pause: true })


      await act(async () => {
        pauseRequest.resolve({ message: 'Task paused' })
        await firstPause
      })
      await secondPause
      await flush()


      expect(rendered.current.controlLoading).toEqual({})
      expect(rendered.current.taskStatus.status).toBe('paused')


      await act(async () => {
        await rendered.current.controlTask('resume')
      })
      expect(callApi.mock.calls.filter(([path]) => path === '/course/task/A/resume')).toHaveLength(1)
      expect(rendered.current.controlLoading).toEqual({})
    } finally {
      rendered.cleanup()
    }
  })


  test('releases a failed control request so the same action can be retried', async () => {
    const firstPause = deferred()
    const secondPause = deferred()
    const pauseRequests = [firstPause, secondPause]
    const callApi = vi.fn((path) => {
      if (path === '/course/tasks') return Promise.resolve([])
      if (path === '/course/status/A') return Promise.resolve(status('A', 'running'))
      if (path.startsWith('/course/logs/A?cursor=')) return Promise.resolve(logs('A'))
      if (path === '/course/task/A/pause') return pauseRequests.shift().promise
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const rendered = renderTaskExecution(callApi)


    try {
      act(() => rendered.current.setTaskId('A'))
      await flush()


      let firstAttempt
      act(() => {
        firstAttempt = rendered.current.controlTask('pause')
      })
      expect(rendered.current.controlLoading).toEqual({ pause: true })
      await act(async () => {
        firstPause.reject(new Error('pause failed'))
        await firstAttempt
      })
      await flush()


      expect(rendered.current.controlLoading).toEqual({})
      let secondAttempt
      act(() => {
        secondAttempt = rendered.current.controlTask('pause')
      })
      expect(callApi.mock.calls.filter(([path]) => path === '/course/task/A/pause')).toHaveLength(2)
      await act(async () => {
        secondPause.resolve({ message: 'Task paused' })
        await secondAttempt
      })
      expect(rendered.current.controlLoading).toEqual({})
      expect(rendered.setError).toHaveBeenCalledWith('pause failed')
    } finally {
      rendered.cleanup()
    }
  })


  test('keeps a new task control lock when the previous task request settles', async () => {
    const aPause = deferred()
    const bPause = deferred()
    const callApi = vi.fn((path) => {
      if (path === '/course/tasks') return Promise.resolve([])
      if (path === '/course/status/A') return Promise.resolve(status('A', 'running'))
      if (path === '/course/status/B') return Promise.resolve(status('B', 'running'))
      if (path.startsWith('/course/logs/A?cursor=')) return Promise.resolve(logs('A'))
      if (path.startsWith('/course/logs/B?cursor=')) return Promise.resolve(logs('B'))
      if (path === '/course/task/A/pause') return aPause.promise
      if (path === '/course/task/B/pause') return bPause.promise
      return Promise.reject(new Error(`Unexpected path: ${path}`))
    })
    const rendered = renderTaskExecution(callApi)


    try {
      act(() => rendered.current.setTaskId('A'))
      await flush()
      act(() => {
        void rendered.current.controlTask('pause')
      })
      expect(rendered.current.controlLoading).toEqual({ pause: true })


      act(() => rendered.current.setTaskId('B'))
      await flush()
      act(() => {
        void rendered.current.controlTask('pause')
      })
      expect(callApi.mock.calls.filter(([path]) => path === '/course/task/B/pause')).toHaveLength(1)
      expect(rendered.current.controlLoading).toEqual({ pause: true })


      await act(async () => {
        aPause.resolve({ message: 'Task paused' })
        await Promise.resolve()
        await Promise.resolve()
      })
      await flush()


      expect(rendered.current.taskId).toBe('B')
      expect(rendered.current.controlLoading).toEqual({ pause: true })
      act(() => {
        void rendered.current.controlTask('pause')
      })
      expect(callApi.mock.calls.filter(([path]) => path === '/course/task/B/pause')).toHaveLength(1)


      await act(async () => {
        bPause.resolve({ message: 'Task paused' })
        await Promise.resolve()
        await Promise.resolve()
      })
      await flush()
      expect(rendered.current.controlLoading).toEqual({})
    } finally {
      rendered.cleanup()
    }
  })
})
