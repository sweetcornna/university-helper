import { useCallback, useEffect, useRef, useState } from 'react'

import {
  POLL_INTERVAL_MS,
  upsertBackgroundTaskHistory,
} from '../utils'

export default function useBackgroundTasks(requestChaoxingApi) {
  const pollRef = useRef(null)
  // Client-tracked log cursor: the server now slices statelessly from this
  // offset, so reopening a task / overlapping polls no longer race on a shared
  // server cursor and drop logs. Reset to 0 whenever a task is (re)opened.
  const logCursorRef = useRef(0)
  // Task-scoped in-flight guard: holds the task id whose poll is currently in
  // flight (or ''). It skips a *second poll of the SAME task* (so two overlapping
  // refreshes don't read one cursor and double-append), while still allowing a
  // newly-opened task to poll. Paired with openTaskRef below, which drops stale
  // responses so an in-flight poll for task A can't write A's status/logs/cursor
  // into a freshly-opened task B's view.
  const inFlightRef = useRef('')
  // The currently-open task id; responses for any other id are discarded.
  const openTaskRef = useRef('')

  const [taskId, setTaskId] = useState('')
  const [taskStatus, setTaskStatus] = useState(null)
  const [logs, setLogs] = useState([])
  const [statusLoading, setStatusLoading] = useState(false)

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const refreshTaskStatus = useCallback(async (currentTaskId, { setResultType, setResultMessage, setBackgroundTaskHistory } = {}) => {
    if (!currentTaskId) return
    // Skip only a concurrent poll of the SAME task (prevents one-cursor double
    // append); a different (newly-opened) task is allowed to proceed.
    if (inFlightRef.current === currentTaskId) return
    inFlightRef.current = currentTaskId
    setStatusLoading(true)

    try {
      const [statusResp, logsResp] = await Promise.all([
        requestChaoxingApi(`/task/${currentTaskId}`),
        requestChaoxingApi(`/logs/${currentTaskId}?cursor=${logCursorRef.current}`)
      ])

      // The open task changed while this request was in flight — discard the
      // stale result so it can't overwrite the new task's view or cursor.
      if (openTaskRef.current !== currentTaskId) return

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
      if (Array.isArray(logsResp?.data) && logsResp.data.length > 0) {
        setLogs((prev) => [...prev, ...logsResp.data].slice(-200))
      }
      // Advance to the server-reported cursor so the next poll only fetches new lines.
      if (typeof logsResp?.cursor === 'number') {
        logCursorRef.current = logsResp.cursor
      }

      if (statusData.status === 'completed' || statusData.status === 'error') {
        stopPolling()
      }
    } catch (err) {
      if (setResultType) setResultType('error')
      if (setResultMessage) setResultMessage(err.message || '查询任务状态失败。')
      stopPolling()
    } finally {
      // Only clear if still ours — a newer task's poll may have taken the slot.
      if (inFlightRef.current === currentTaskId) inFlightRef.current = ''
      setStatusLoading(false)
    }
  }, [requestChaoxingApi, stopPolling])

  const openBackgroundTask = useCallback(async (nextTaskId, callbacks) => {
    const normalizedTaskId = String(nextTaskId || '').trim()
    if (!normalizedTaskId) return false
    // Mark B as the open task BEFORE refreshing so any in-flight poll for the
    // previous task is treated as stale and its response is dropped.
    openTaskRef.current = normalizedTaskId
    setTaskId(normalizedTaskId)
    setTaskStatus(null)
    setLogs([])
    logCursorRef.current = 0
    await refreshTaskStatus(normalizedTaskId, callbacks)
    return true
  }, [refreshTaskStatus])

  // Keep openTaskRef in sync for interval-driven polls (openBackgroundTask sets
  // it eagerly; this covers taskId changes from any other path).
  useEffect(() => {
    openTaskRef.current = taskId
  }, [taskId])

  // Poll effect: when taskId changes, start/stop 3s polling
  useEffect(() => {
    if (!taskId) return undefined
    stopPolling()
    pollRef.current = setInterval(() => {
      refreshTaskStatus(taskId)
    }, POLL_INTERVAL_MS)
    return stopPolling
  }, [refreshTaskStatus, stopPolling, taskId])

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
