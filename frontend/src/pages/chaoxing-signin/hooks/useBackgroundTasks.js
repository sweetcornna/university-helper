import { useCallback, useEffect, useRef, useState } from 'react'

import {
  POLL_INTERVAL_MS,
  upsertBackgroundTaskHistory,
} from '../utils'

export default function useBackgroundTasks(requestChaoxingApi) {
  const pollRef = useRef(null)

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
        requestChaoxingApi(`/logs/${currentTaskId}`)
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
