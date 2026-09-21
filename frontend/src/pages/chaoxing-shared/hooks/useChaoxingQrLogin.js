import { useCallback, useEffect, useRef, useState } from 'react'

import { QR_POLL_INTERVAL_MS, QR_STATUS, isQrInFlight } from '../utils'

/**
 * Drives the 学习通 QR-code login: fetch an image, poll until the phone
 * confirms, then report the authenticated account.
 *
 * The backend returns a ready-to-render base64 PNG, so nothing here needs a QR
 * generation library — the panel just renders it as a data URI. The same goes
 * for expiry: the server mints a replacement and rides it back on a poll
 * response, so a slow scan can still succeed.
 *
 * @param chaoxingRequest  `(path, options) => Promise<payload>` — the page's
 *                 fetch wrapper, scoped to the **Chaoxing** API root, so it
 *                 receives `/qr-login` and must produce
 *                 `/api/v1/chaoxing/qr-login`. Both pages have their own
 *                 wrapper, so it is injected rather than imported.
 * @param onSuccess  Called once with the final response, carrying `username`.
 */
export default function useChaoxingQrLogin({ chaoxingRequest, onSuccess }) {
  const [qrCode, setQrCode] = useState('')
  const [status, setStatus] = useState(QR_STATUS.IDLE)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const sessionIdRef = useRef('')
  const pollRef = useRef(null)

  // Held in a ref so an inline arrow from the caller doesn't restart polling.
  const onSuccessRef = useRef(onSuccess)
  useEffect(() => {
    onSuccessRef.current = onSuccess
  }, [onSuccess])

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  // Never leave an interval behind when the panel unmounts.
  useEffect(() => stopPolling, [stopPolling])

  const reset = useCallback(() => {
    stopPolling()
    sessionIdRef.current = ''
    setQrCode('')
    setStatus(QR_STATUS.IDLE)
    setMessage('')
    setError('')
  }, [stopPolling])

  const poll = useCallback(
    async (sessionId) => {
      try {
        const resp = await chaoxingRequest(`/qr-login/${sessionId}`)
        const next = String(resp?.status || '')

        // Render the refreshed image when the previous code expired.
        if (resp?.qr_code) setQrCode((prev) => (prev === resp.qr_code ? prev : resp.qr_code))
        if (resp?.message) setMessage(resp.message)

        if (next === QR_STATUS.SUCCESS) {
          stopPolling()
          setStatus(QR_STATUS.SUCCESS)
          onSuccessRef.current?.(resp)
          return
        }

        if (next === QR_STATUS.FAILED) {
          stopPolling()
          setStatus(QR_STATUS.FAILED)
          setError(resp?.message || '扫码登录失败，请重试。')
          return
        }

        setStatus(next || QR_STATUS.PENDING)
      } catch (err) {
        // Stop rather than hammer a failing endpoint; the user can retry.
        stopPolling()
        setStatus(QR_STATUS.FAILED)
        setError(err?.message || '扫码登录状态查询失败，请重试。')
      }
    },
    [chaoxingRequest, stopPolling]
  )

  const start = useCallback(async () => {
    stopPolling()
    setError('')
    setMessage('')
    setQrCode('')
    setStatus(QR_STATUS.LOADING)

    try {
      const resp = await chaoxingRequest('/qr-login', { method: 'POST' })
      const sessionId = String(resp?.session_id || '')
      if (!sessionId || !resp?.qr_code) {
        throw new Error('二维码登录响应无效。')
      }
      sessionIdRef.current = sessionId
      setQrCode(resp.qr_code)
      setMessage(resp?.message || '')
      setStatus(QR_STATUS.PENDING)
    } catch (err) {
      setStatus(QR_STATUS.FAILED)
      setError(err?.message || '二维码生成失败，请稍后重试。')
    }
  }, [chaoxingRequest, stopPolling])

  const cancel = useCallback(async () => {
    const sessionId = sessionIdRef.current
    reset()
    if (!sessionId) return
    try {
      await chaoxingRequest(`/qr-login/${sessionId}`, { method: 'DELETE' })
    } catch {
      // Best effort: the server sweeps abandoned sessions on its own TTL.
    }
  }, [chaoxingRequest, reset])

  // Poll only while the scan is live. Leaving the interval up after a terminal
  // status would keep hitting the endpoint for a session that is already over.
  useEffect(() => {
    if (!isQrInFlight(status)) return undefined
    const sessionId = sessionIdRef.current
    if (!sessionId) return undefined

    pollRef.current = setInterval(() => {
      void poll(sessionId)
    }, QR_POLL_INTERVAL_MS)
    return stopPolling
  }, [status, poll, stopPolling])

  return { qrCode, status, message, error, start, cancel, reset }
}
