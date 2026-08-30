import { useCallback, useEffect, useRef, useState } from 'react'

import {
  CHAOXING_SETTINGS_KEY,
  DEFAULT_CHECK_INTERVAL_MINUTES,
  AUTO_SIGN_TASK_COOLDOWN_MS,
  clampCheckInterval,
} from '../utils'

export default function useAutoSignin(form, executeSignin, requestChaoxingApi, { setResultType, setResultMessage, setSigninTasks, redirectingRef }) {
  const autoCheckRef = useRef(null)
  const countdownRef = useRef(null)
  const autoSignedTaskCacheRef = useRef(new Map())
  // Track ownership by scheduler generation so a new generation can start
  // while an invalidated request from the previous generation is still in flight.
  const autoSigningRef = useRef(null)
  const schedulerGenerationRef = useRef(0)
  const formRef = useRef(form)
  const executeSigninRef = useRef(executeSignin)

  // Keep the scheduler stable while still using the latest form and sign-in
  // callback when the next cycle starts.
  formRef.current = form
  executeSigninRef.current = executeSignin

  const [autoSignin, setAutoSignin] = useState(false)
  const [autoSignFilter, setAutoSignFilter] = useState('all')
  const [checkInterval, setCheckInterval] = useState(DEFAULT_CHECK_INTERVAL_MINUTES)
  const [nextCheckCountdown, setNextCheckCountdown] = useState(0)
  const [todayStats, setTodayStats] = useState({ total: 0, success: 0, failed: 0 })

  const stopAutoCheck = useCallback(() => {
    schedulerGenerationRef.current += 1
    if (countdownRef.current) {
      clearInterval(countdownRef.current)
      countdownRef.current = null
    }
    if (autoCheckRef.current) {
      clearInterval(autoCheckRef.current)
      autoCheckRef.current = null
    }
    setNextCheckCountdown(0)
  }, [])

  // Load settings from localStorage
  useEffect(() => {
    try {
      const raw = localStorage.getItem(CHAOXING_SETTINGS_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw)
      if (typeof parsed.autoSignin === 'boolean') {
        setAutoSignin(parsed.autoSignin)
      }
      if (typeof parsed.autoSignFilter === 'string' && parsed.autoSignFilter) {
        setAutoSignFilter(parsed.autoSignFilter)
      }
      if (parsed.checkInterval !== undefined && parsed.checkInterval !== null) {
        setCheckInterval(clampCheckInterval(parsed.checkInterval))
      }
    } catch (err) {
      console.warn('Failed to load chaoxing settings:', err)
    }
  }, [])

  // Save settings to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(
        CHAOXING_SETTINGS_KEY,
        JSON.stringify({
          autoSignin,
          autoSignFilter,
          checkInterval: clampCheckInterval(checkInterval)
        })
      )
    } catch (err) {
      console.warn('Failed to save chaoxing settings:', err)
    }
  }, [autoSignin, autoSignFilter, checkInterval])

  const runAutoSigninCycle = useCallback(async (generation) => {
    if (
      generation !== schedulerGenerationRef.current ||
      autoSigningRef.current === generation ||
      redirectingRef.current ||
      !autoSignin
    ) {
      return
    }

    const username = formRef.current.username.trim()
    const password = formRef.current.password
    if (!username || !password) {
      setResultType('error')
      setResultMessage('自动签到已开启，但账号或密码为空。')
      return
    }

    autoSigningRef.current = generation
    try {
      const resp = await requestChaoxingApi('/tasks')
      if (generation !== schedulerGenerationRef.current) return

      const pendingTasks = Array.isArray(resp?.data) ? resp.data : []
      setSigninTasks(pendingTasks)

      const filteredTasks = pendingTasks.filter((task) => {
        if (task?.actionable === false || task?.source === 'background') return false
        const taskType = String(task?.type || 'normal')
        if (autoSignFilter === 'all') return true
        if (autoSignFilter === 'gesture' || autoSignFilter === 'code') {
          return taskType === 'normal'
        }
        return taskType === autoSignFilter
      })

      if (filteredTasks.length === 0) return

      const now = Date.now()
      let successCount = 0

      for (const task of filteredTasks) {
        if (generation !== schedulerGenerationRef.current) return

        const taskType = String(task?.type || 'normal')
        const taskKey = `${task?.taskId || task?.activeId || task?.courseId || task?.courseName || 'task'}:${taskType}`
        const lastTriedAt = autoSignedTaskCacheRef.current.get(taskKey) || 0
        if (now - lastTriedAt < AUTO_SIGN_TASK_COOLDOWN_MS) continue
        autoSignedTaskCacheRef.current.set(taskKey, now)

        const result = await executeSigninRef.current(task?.courseId || null, taskType, { silent: true })
        if (generation !== schedulerGenerationRef.current) return

        if (result.status) {
          successCount += 1
        }
      }

      if (generation === schedulerGenerationRef.current && successCount > 0) {
        setResultType('success')
        setResultMessage(`自动签到完成，成功处理 ${successCount} 个任务。`)
      }
    } catch (err) {
      if (generation !== schedulerGenerationRef.current) return

      setResultType('error')
      setResultMessage(err.message || '自动签到检查失败。')
    } finally {
      if (autoSigningRef.current === generation) {
        autoSigningRef.current = null
      }
    }
  }, [autoSignin, autoSignFilter, requestChaoxingApi, setResultType, setResultMessage, setSigninTasks, redirectingRef])

  // Auto-signin cycle + countdown effect
  useEffect(() => {
    if (!autoSignin) {
      stopAutoCheck()
      return undefined
    }

    const normalizedInterval = clampCheckInterval(checkInterval)
    if (normalizedInterval !== checkInterval) {
      setCheckInterval(normalizedInterval)
      return undefined
    }

    const intervalMs = normalizedInterval * 60 * 1000
    const generation = schedulerGenerationRef.current + 1
    schedulerGenerationRef.current = generation
    setNextCheckCountdown(normalizedInterval * 60)

    void runAutoSigninCycle(generation)

    countdownRef.current = setInterval(() => {
      if (schedulerGenerationRef.current !== generation) return

      setNextCheckCountdown(prev => Math.max(0, prev - 1))
    }, 1000)

    autoCheckRef.current = setInterval(() => {
      if (schedulerGenerationRef.current !== generation) return

      void runAutoSigninCycle(generation)
      if (schedulerGenerationRef.current !== generation) return

      setNextCheckCountdown(normalizedInterval * 60)
    }, intervalMs)

    return () => {
      stopAutoCheck()
    }
  }, [autoSignin, checkInterval, runAutoSigninCycle, stopAutoCheck])

  return {
    autoSignin,
    setAutoSignin,
    autoSignFilter,
    setAutoSignFilter,
    checkInterval,
    setCheckInterval,
    nextCheckCountdown,
    todayStats,
    setTodayStats,
    stopAutoCheck,
  }
}
