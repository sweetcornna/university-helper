import { useCallback, useEffect, useRef, useState } from 'react'
import {
  toNum, toTimestamp, normalizeTaskItem, mergeTaskHistory,
  DONE_STATUSES, RESTORE_STATUSES, POLL_MS,
} from '../utils'


export default function useTaskExecution({ callApi, setError, setNotice, pollRef, stopPolling }) {


  const logCursorRef = useRef(0)


  const [taskId, setTaskId] = useState('')


  const [taskStatus, setTaskStatus] = useState(null)


  const [logs, setLogs] = useState([])


  const [logCursor, setLogCursor] = useState(0)


  const [taskHistory, setTaskHistory] = useState([])


  const [loading, setLoading] = useState(false)


  useEffect(() => {


    logCursorRef.current = logCursor


  }, [logCursor])



  const appendLogs = useCallback((incoming) => {


    if (!Array.isArray(incoming) || incoming.length === 0) return


    setLogs((prev) => {


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


  }, [])


  const loadTaskSnapshot = useCallback(


    async (id, options = {}) => {


      const targetId = String(id || '').trim()


      if (!targetId) return


      const shouldResetLogs = Boolean(options.resetLogs)


      const cursor = shouldResetLogs ? 0 : logCursorRef.current


      if (shouldResetLogs) {


        setLogs([])


        setLogCursor(0)


        logCursorRef.current = 0


      }


      const statusResp = await callApi(`/course/status/${targetId}`)


      if (!statusResp) return


      setTaskStatus(statusResp)


      setTaskHistory((prev) =>


        mergeTaskHistory(


          prev,


          {


            ...statusResp,


            task_id: targetId,


            updated_at: statusResp.updated_at || statusResp.updatedAt || new Date().toISOString()


          },


          true


        )


      )


      const logsResp = await callApi(`/course/logs/${targetId}?cursor=${cursor}`)


      if (logsResp) {


        const items = (logsResp.data || []).map((item) => ({


          timestamp: item.timestamp || new Date().toISOString(),


          level: item.level || 'info',


          message: item.message || ''


        }))


        appendLogs(items)


        setLogCursor(toNum(logsResp.cursor, cursor + items.length))


      }


      const statusText = String(statusResp?.status || '').toLowerCase()


      if (DONE_STATUSES.has(statusText)) {


        setLoading(false)


        stopPolling()


      }


    },


    [appendLogs, callApi, stopPolling]


  )


  // Restore tasks on mount
  useEffect(() => {


    let active = true


    const restoreTasks = async () => {


      try {


        const resp = await callApi('/course/tasks')


        if (!resp || !active) return


        const rawTasks = Array.isArray(resp) ? resp : resp?.tasks || resp?.data || []


        const normalizedTasks = rawTasks


          .map(normalizeTaskItem)


          .filter(Boolean)


          .sort((a, b) => toTimestamp(b.updated_at) - toTimestamp(a.updated_at))


        if (!active) return


        setTaskHistory(normalizedTasks)


        if (normalizedTasks.length === 0) return


        const restoringTask = normalizedTasks.find((item) => RESTORE_STATUSES.has(item.status)) || normalizedTasks[0]


        if (!restoringTask?.task_id) return


        setTaskId(restoringTask.task_id)


        await loadTaskSnapshot(restoringTask.task_id, { resetLogs: true })


      } catch (err) {


        if (!active) return


        setError((prev) => prev || err?.message || '恢复任务状态失败。')


      }


    }


    void restoreTasks()


    return () => {


      active = false


    }


  }, [callApi, loadTaskSnapshot, setError])


  const selectTaskFromHistory = useCallback(


    async (id) => {


      const targetId = String(id || '').trim()


      if (!targetId) return


      setError('')


      setNotice('')


      setTaskId(targetId)


      stopPolling()


      try {


        await loadTaskSnapshot(targetId, { resetLogs: true })


      } catch (err) {


        setError(err?.message || '读取任务详情失败。')


      }


    },


    [loadTaskSnapshot, stopPolling, setError, setNotice]


  )


  // Polling effect
  useEffect(() => {


    if (!taskId) return undefined


    const run = async () => {


      try {


        await loadTaskSnapshot(taskId)


      } catch (err) {


        setError(err?.message || '获取任务状态失败。')


      }


    }


    void run()


    stopPolling()


    pollRef.current = setInterval(() => {


      void run()


    }, POLL_MS)


    return () => stopPolling()


    // pollRef is a mutable ref; including it in deps would not change the
    // effect's identity and only adds noise. Lint rule is overzealous here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadTaskSnapshot, stopPolling, taskId, setError])


  const controlTask = useCallback(


    async (action) => {


      if (!taskId) return


      try {


        const resp = await callApi(`/course/task/${taskId}/${action}`, { method: 'POST' })


        if (!resp) return


        setNotice(resp.message || '操作成功。')


        await loadTaskSnapshot(taskId)


      } catch (err) {


        setError(err?.message || '任务控制失败。')


      }


    },


    [callApi, loadTaskSnapshot, taskId, setError, setNotice]


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
