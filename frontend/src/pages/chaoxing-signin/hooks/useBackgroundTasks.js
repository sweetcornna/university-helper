import { useCallback, useEffect, useRef, useState } from 'react'

import {
  POLL_INTERVAL_MS,
  upsertBackgroundTaskHistory,
} from '../utils'

export default function useBackgroundTasks(requestChaoxingApi) {
  const pollRef = useRef(null)
  // Monotonic generation for every open/clear operation. Task ids can be
  // reused, so the id alone cannot distinguish an old request from a reopened
  // task with the same id.
  const taskGenerationRef = useRef(0)
  // Client-tracked log cursor: the server now slices statelessly from this
  // offset, so reopening a task / overlapping polls no longer race on a shared
  // server cursor and drop logs. Reset to 0 whenever a task is (re)opened.
  const logCursorRef = useRef(0)
  // Task-scoped in-flight guard: a new generation may poll even when its task
  // id is the same as an older generation still in flight.
  const inFlightRef = useRef(null)
  // The currently-open task identity; responses for any other id or generation
  // are discarded.
  const openTaskRef = useRef({ taskId: '', generation: 0 })

  const [taskId, setTaskIdState] = useState('')
  const [taskGeneration, setTaskGeneration] = useState(0)
  const [taskStatus, setTaskStatus] = useState(null)
  const [logs, setLogs] = useState([])
  const [statusLoading, setStatusLoading] = useState(false)

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const invalidateTaskGeneration = useCallback(() => {
    const generation = taskGenerationRef.current + 1
    taskGenerationRef.current = generation
    openTaskRef.current = { taskId: '', generation }
    inFlightRef.current = null
    setTaskGeneration(generation)
    return generation
  }, [])

  const setTaskId = useCallback((nextTaskId) => {
    if (nextTaskId === '') {
      invalidateTaskGeneration()
      setStatusLoading(false)
    }
    setTaskIdState(nextTaskId)
  }, [invalidateTaskGeneration])

  const refreshTaskStatus = useCallback(async (
    currentTaskId,
    { setResultType, setResultMessage, setBackgroundTaskHistory } = {},
    expectedGeneration = openTaskRef.current.generation,
  ) => {
    if (!currentTaskId) return

    const generation = expectedGeneration
    const isCurrentTask = () => {
      const openTask = openTaskRef.current
      return openTask.taskId === currentTaskId && openTask.generation === generation
    }
    const isCurrentPoll = () => {
      const inFlight = inFlightRef.current
      return isCurrentTask() && inFlight?.taskId === currentTaskId && inFlight.generation === generation
    }

    // Reject calls for an id/generation that is no longer open, then skip only
    // a concurrent poll from this exact generation.
    if (!isCurrentTask() || isCurrentPoll()) return

    inFlightRef.current = { taskId: currentTaskId, generation }
    setStatusLoading(true)

    try {
      // Start both requests together, but keep status as the primary chain.
      // Convert the log rejection immediately so a status failure can finish
      // without leaving an unhandled log rejection behind.
      const statusPromise = Promise.resolve(requestChaoxingApi(`/task/${currentTaskId}`))
      let logsPromise
      try {
        logsPromise = Promise.resolve(
          requestChaoxingApi(`/logs/${currentTaskId}?cursor=${logCursorRef.current}`)
        ).then(
          (value) => ({ ok: true, value }),
          (error) => ({ ok: false, error })
        )
      } catch (error) {
        logsPromise = Promise.resolve({ ok: false, error })
      }

      const statusResp = await statusPromise

      // The open task or generation changed while this request was in flight —
      // discard the stale result so it cannot overwrite the new task's view.
      if (!isCurrentTask()) return

      const statusData = statusResp?.data || {}
      setTaskStatus(statusData)
      if (setBackgroundTaskHistory) {
        setBackgroundTaskHistory((prev) =>
          upsertBackgroundTaskHistory(prev, {
            ...statusData,
            task_id: currentTaskId
          })
        )
      }

      if (statusData.status === 'completed' || statusData.status === 'error') {
        stopPolling()
      }

      const logsResult = await logsPromise

      // The open task, generation, or in-flight poll changed while logs were
      // loading — discard the stale result so it cannot overwrite the new
      // task's logs or cursor.
      if (!isCurrentPoll()) return

      if (!logsResult.ok) {
        // Logs are supplementary to status. Keep the current task alive and
        // make the log-only failure visible without reporting task failure.
        console.error(`Failed to fetch background task logs for ${currentTaskId}:`, logsResult.error)
      } else {
        const logsResp = logsResult.value
        if (Array.isArray(logsResp?.data) && logsResp.data.length > 0) {
          setLogs((prev) => [...prev, ...logsResp.data].slice(-200))
        }
        // Advance to the server-reported cursor so the next poll only fetches new lines.
        if (typeof logsResp?.cursor === 'number') {
          logCursorRef.current = logsResp.cursor
        }
      }
    } catch (err) {
      if (!isCurrentPoll()) return
      if (setResultType) setResultType('error')
      if (setResultMessage) setResultMessage(err.message || '查询任务状态失败。')
      stopPolling()
    } finally {
      // Only clear if this exact generation still owns the poll slot — a newer
      // generation may have taken it, including when the task id is reused.
      if (isCurrentPoll()) {
        inFlightRef.current = null
        if (isCurrentTask()) setStatusLoading(false)
      }
    }
  }, [requestChaoxingApi, stopPolling])

  const openBackgroundTask = useCallback(async (nextTaskId, callbacks) => {
    const normalizedTaskId = String(nextTaskId || '').trim()
    if (!normalizedTaskId) return false

    const generation = taskGenerationRef.current + 1
    taskGenerationRef.current = generation
    // Mark the new task identity BEFORE refreshing so any in-flight poll for
    // the previous generation is treated as stale and its response is dropped.
    openTaskRef.current = { taskId: normalizedTaskId, generation }
    setTaskIdState(normalizedTaskId)
    setTaskGeneration(generation)
    setTaskStatus(null)
    setLogs([])
    logCursorRef.current = 0
    await refreshTaskStatus(normalizedTaskId, callbacks, generation)
    return true
  }, [refreshTaskStatus])

  // Keep openTaskRef in sync for taskId changes from any other path. The public
  // setTaskId('') wrapper invalidates eagerly; this also covers functional state
  // updates and preserves the setter's existing API shape.
  useEffect(() => {
    if (openTaskRef.current.taskId === taskId) return

    const generation = taskGenerationRef.current + 1
    taskGenerationRef.current = generation
    openTaskRef.current = { taskId, generation }
    setTaskGeneration(generation)
    if (!taskId) {
      inFlightRef.current = null
      logCursorRef.current = 0
      setStatusLoading(false)
    }
  }, [taskId])

  // Poll effect: when taskId or its generation changes, start/stop 3s polling.
  useEffect(() => {
    if (!taskId) return undefined
    stopPolling()
    pollRef.current = setInterval(() => {
      refreshTaskStatus(taskId)
    }, POLL_INTERVAL_MS)
    return stopPolling
  }, [refreshTaskStatus, stopPolling, taskId, taskGeneration])

  return {
    taskId,
    setTaskId,
    taskStatus,
    setTaskStatus,
    logs,
    setLogs,
    statusLoading,
    refreshTaskStatus,
    openBackgroundTask,
    stopPolling,
  }
}
