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
    setStatusLoading(true)

    try {
      const [statusResp, logsResp] = await Promise.all([
        requestChaoxingApi(`/task/${currentTaskId}`),
        requestChaoxingApi(`/logs/${currentTaskId}?cursor=${logCursorRef.current}`)
      ])

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
      setStatusLoading(false)
    }
  }, [requestChaoxingApi, stopPolling])

  const openBackgroundTask = useCallback(async (nextTaskId, callbacks) => {
    const normalizedTaskId = String(nextTaskId || '').trim()
    if (!normalizedTaskId) return false
    setTaskId(normalizedTaskId)
    setTaskStatus(null)
    setLogs([])
    logCursorRef.current = 0
    await refreshTaskStatus(normalizedTaskId, callbacks)
    return true
  }, [refreshTaskStatus])

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
