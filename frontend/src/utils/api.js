import { getToken, removeToken } from './auth'

const API_BASE =
  import.meta.env.VITE_API_BASE ||
  import.meta.env.VITE_API_BASE_URL ||
  '/api/v1'
const DEFAULT_TIMEOUT_MS = 20000

// Custom event that the app shell (App.jsx / a top-level effect) can listen
// to in order to navigate to /login on session expiry — keeps api.js free of
// react-router coupling.
export const AUTH_EXPIRED_EVENT = 'auth:expired'

const parsePayload = async (response) => {
  const text = await response.text()
  if (!text) return {}
  try {
    return JSON.parse(text)
  } catch (_) {
    return { message: text }
  }
}

const formatDetail = (detail) => {
  if (!detail) return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (!item) return ''
        if (typeof item === 'string') return item
        const loc = Array.isArray(item.loc)
          ? item.loc.filter((seg) => seg !== 'body' && seg !== 'query').join('.')
          : ''
        const msg = item.msg || item.message || ''
        if (!msg) return loc
        return loc ? `${loc}: ${msg}` : msg
      })
      .filter(Boolean)
    return messages.join('；')
  }
  if (typeof detail === 'object') {
    return detail.msg || detail.message || ''
  }
  return String(detail)
}

const pickErrorMessage = (payload, status) => {
  if (!payload) return `请求失败（${status}）`
  return (
    payload.message ||
    formatDetail(payload.detail) ||
    payload.error ||
    payload.msg ||
    payload.data?.message ||
    `请求失败（${status}）`
  )
}

const handleUnauthorized = () => {
  removeToken()
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT))
  }
}

export class ApiError extends Error {
  constructor(message, { status, payload } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

export const api = async (endpoint, options = {}) => {
  const token = getToken()
  const timeoutMs = Number(options.timeoutMs ?? DEFAULT_TIMEOUT_MS)
  const hasCustomSignal = Boolean(options.signal)
  const controller = hasCustomSignal ? null : new AbortController()
  const timeoutId =
    !hasCustomSignal && Number.isFinite(timeoutMs) && timeoutMs > 0
      ? setTimeout(() => controller?.abort(), timeoutMs)
      : null

  const headers = {
    'Content-Type': 'application/json',
    ...(token && { Authorization: `Bearer ${token}` }),
    ...options.headers,
  }

  const requestOptions = {
    ...options,
    headers,
    ...(hasCustomSignal ? {} : { signal: controller.signal }),
  }
  delete requestOptions.timeoutMs

  try {
    const response = await fetch(`${API_BASE}${endpoint}`, requestOptions)
    const payload = await parsePayload(response)

    // Only treat 401 as session expiry when this request was actually
    // authenticated. A 401 on /auth/login etc. is "wrong credentials" and
    // must surface the server's message — not the generic expiry redirect.
    if (response.status === 401 && token) {
      handleUnauthorized()
      throw new ApiError(
        pickErrorMessage(payload, response.status) || '登录状态已失效，请重新登录。',
        { status: 401, payload },
      )
    }

    if (!response.ok || payload?.status === false) {
      throw new ApiError(pickErrorMessage(payload, response.status), {
        status: response.status,
        payload,
      })
    }
    return payload
  } catch (error) {
    // Only remap AbortError when *we* set up the timer. If the caller passed
    // their own AbortController, surface their abort unchanged.
    if (error?.name === 'AbortError' && !hasCustomSignal) {
      throw new ApiError('请求超时，请稍后重试。', { status: 0 })
    }
    throw error
  } finally {
    if (timeoutId) {
      clearTimeout(timeoutId)
    }
  }
}
