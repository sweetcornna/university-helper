import { useCallback, useEffect, useRef, useState } from 'react'
import {
  toNum, toTimestamp, normalizeTaskItem, mergeTaskHistory,
  DONE_STATUSES, RESTORE_STATUSES, POLL_MS,
} from '../utils'


export default function useTaskExecution({ callApi, setError, setNotice, pollRef, stopPolling }) {


  const logCursorRef = useRef(0)


  const taskIdRef = useRef('')


  const taskGenerationRef = useRef(0)


  const pollInFlightRef = useRef(null)


  const [taskId, setTaskIdState] = useState('')


  const [taskStatus, setTaskStatus] = useState(null)


  const [logs, setLogs] = useState([])


  const [logCursor, setLogCursor] = useState(0)


  const [taskHistory, setTaskHistory] = useState([])


  const [loading, setLoading] = useState(false)


  const isCurrentGeneration = useCallback((generation) => generation === taskGenerationRef.current, [])


  const isCurrentTask = useCallback((generation, targetId) => (
    isCurrentGeneration(generation) &&
    (!taskIdRef.current || taskIdRef.current === targetId)
  ), [isCurrentGeneration])


  const setTaskId = useCallback((nextId) => {
    const resolvedId = typeof nextId === 'function' ? nextId(taskIdRef.current) : nextId
    const normalizedId = String(resolvedId || '').trim()


    if (normalizedId !== taskIdRef.current) {
      taskGenerationRef.current += 1
      taskIdRef.current = normalizedId
      setLogs([])
      setLogCursor(0)
      logCursorRef.current = 0
    }


    setTaskIdState(normalizedId)
  }, [])


  useEffect(() => {


    logCursorRef.current = logCursor


  }, [logCursor])



  const appendLogs = useCallback((incoming, options = {}) => {


    if (!Array.isArray(incoming) || incoming.length === 0) return


    const generation = options.generation ?? taskGenerationRef.current
    const targetId = options.taskId ?? taskIdRef.current


    setLogs((prev) => {


      if (!isCurrentTask(generation, targetId)) return prev


      const merged = [...prev, ...incoming]


      const seen = new Set()


      const deduped = []


      for (const item of merged) {


        const key = `${item.timestamp || ''}|${item.level || ''}|${item.message || ''}`


        if (seen.has(key)) continue


        seen.add(key)


        deduped.push(item)


      }


      return deduped.slice(-1000)


    })


  }, [isCurrentTask])


  const loadTaskSnapshot = useCallback(


    async (id, options = {}) => {


      const targetId = String(id || '').trim()


      if (!targetId) return


      const generation = taskGenerationRef.current


      if (!isCurrentTask(generation, targetId)) return


      const shouldResetLogs = Boolean(options.resetLogs)


      const cursor = shouldResetLogs ? 0 : logCursorRef.current


      if (shouldResetLogs) {


        setLogs([])


        setLogCursor(0)


        logCursorRef.current = 0


      }


      const statusResp = await callApi(`/course/status/${targetId}`)


      if (!statusResp || !isCurrentTask(generation, targetId)) return


      setTaskStatus((prev) => (isCurrentTask(generation, targetId) ? statusResp : prev))


      setTaskHistory((prev) =>


        isCurrentTask(generation, targetId)
          ? mergeTaskHistory(


          prev,


          {


            ...statusResp,


            task_id: targetId,


            updated_at: statusResp.updated_at || statusResp.updatedAt || new Date().toISOString()


          },


          true


          )
          : prev


      )


      const logsResp = await callApi(`/course/logs/${targetId}?cursor=${cursor}`)


      if (logsResp && isCurrentTask(generation, targetId)) {


        const items = (logsResp.data || []).map((item) => ({


          timestamp: item.timestamp || new Date().toISOString(),


          level: item.level || 'info',


          message: item.message || ''


        }))


        appendLogs(items, { generation, taskId: targetId })


        const nextCursor = toNum(logsResp.cursor, cursor + items.length)
        setLogCursor((prev) => (isCurrentTask(generation, targetId) ? nextCursor : prev))


      }


      const statusText = String(statusResp?.status || '').toLowerCase()


      if (DONE_STATUSES.has(statusText) && isCurrentTask(generation, targetId)) {


        setLoading((prev) => (isCurrentTask(generation, targetId) ? false : prev))


        stopPolling()


      }


    },


    [appendLogs, callApi, isCurrentTask, stopPolling]


  )


  const runTaskSnapshot = useCallback(
    async (id, options = {}, fallbackError = '获取任务状态失败。') => {
      const targetId = String(id || '').trim()
      if (!targetId) return


      const generation = taskGenerationRef.current
      if (!isCurrentTask(generation, targetId)) return
      if (
        pollInFlightRef.current?.generation === generation &&
        pollInFlightRef.current?.taskId === targetId
      ) return


      const inFlight = { generation, taskId: targetId }
      pollInFlightRef.current = inFlight
      try {
        await loadTaskSnapshot(targetId, options)
      } catch (err) {
        if (isCurrentTask(generation, targetId)) {
          setError(err?.message || fallbackError)
        }
      } finally {
        if (pollInFlightRef.current === inFlight) {
          pollInFlightRef.current = null
        }
      }
    },
    [isCurrentTask, loadTaskSnapshot, setError]
  )


  // Restore tasks on mount
  useEffect(() => {


    let active = true
    const restoreGeneration = taskGenerationRef.current


    const restoreTasks = async () => {


      try {


        const resp = await callApi('/course/tasks')


        if (!resp || !active || !isCurrentGeneration(restoreGeneration)) return


        const rawTasks = Array.isArray(resp) ? resp : resp?.tasks || resp?.data || []


        const normalizedTasks = rawTasks


          .map(normalizeTaskItem)


          .filter(Boolean)


          .sort((a, b) => toTimestamp(b.updated_at) - toTimestamp(a.updated_at))


        if (!active || !isCurrentGeneration(restoreGeneration)) return


        setTaskHistory(normalizedTasks)


        if (normalizedTasks.length === 0) return


        const restoringTask = normalizedTasks.find((item) => RESTORE_STATUSES.has(item.status)) || normalizedTasks[0]


        if (!restoringTask?.task_id) return


        setTaskId(restoringTask.task_id)




      } catch (err) {


        if (!active || !isCurrentGeneration(restoreGeneration)) return


        setError((prev) => prev || err?.message || '恢复任务状态失败。')


      }


    }


    void restoreTasks()


    return () => {


      active = false


    }


  }, [callApi, isCurrentGeneration, setError, setTaskId])


  const selectTaskFromHistory = useCallback(


    (id) => {


      const targetId = String(id || '').trim()


      if (!targetId) return


      setError('')


      setNotice('')


      const isSameTask = targetId === taskIdRef.current
      setTaskId(targetId)


      stopPolling()


      if (isSameTask) {
        void runTaskSnapshot(targetId, { resetLogs: true }, '读取任务详情失败。')
      }




    },


    [runTaskSnapshot, setTaskId, stopPolling, setError, setNotice]


  )


  // Polling effect
  useEffect(() => {


    if (!taskId) return undefined


    const targetId = taskId


    void runTaskSnapshot(targetId)


    stopPolling()


    pollRef.current = setInterval(() => {


      void runTaskSnapshot(targetId)


    }, POLL_MS)


    return () => stopPolling()


    // pollRef is a mutable ref; including it in deps would not change the
    // effect's identity and only adds noise. Lint rule is overzealous here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runTaskSnapshot, stopPolling, taskId])


  const controlTask = useCallback(


    async (action) => {


      if (!taskId) return


      const generation = taskGenerationRef.current
      const targetId = taskId


      try {


        const resp = await callApi(`/course/task/${targetId}/${action}`, { method: 'POST' })


        if (!resp || !isCurrentTask(generation, targetId)) return


        setNotice(resp.message || '操作成功。')


        await loadTaskSnapshot(targetId)


      } catch (err) {


        if (isCurrentTask(generation, targetId)) {
          setError(err?.message || '任务控制失败。')
        }


      }


    },


    [callApi, isCurrentTask, loadTaskSnapshot, taskId, setError, setNotice]


  )


  return {
    taskId, setTaskId,
    taskStatus, setTaskStatus,
    logs, setLogs,
    logCursor, setLogCursor,
    logCursorRef,
    taskHistory, setTaskHistory,
    loading, setLoading,
    appendLogs,
    loadTaskSnapshot,
    selectTaskFromHistory,
    controlTask,
  }


}
