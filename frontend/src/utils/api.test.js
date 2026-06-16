import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { api, ApiError, AUTH_EXPIRED_EVENT } from './api'
import { getToken, setToken, removeToken } from './auth'

const jsonResponse = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  text: async () => JSON.stringify(body),
})

describe('api() auth handling', () => {
  let expiredEvents
  let onExpired

  beforeEach(() => {
    removeToken()
    setToken('valid.jwt.token')
    expiredEvents = 0
    onExpired = () => {
      expiredEvents += 1
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired)
  })

  afterEach(() => {
    window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired)
    removeToken()
    vi.restoreAllMocks()
  })

  // F62: a soft auth failure (HTTP 200 + { status:false, message:'token...' })
  // must be handled exactly like a 401 — token cleared + AUTH_EXPIRED dispatched.
  test('treats HTTP 200 status:false token-error body as a session expiry', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse(200, { status: false, message: '登录态失效，请重新登录' }))
    )

    await expect(api('/course/status/1')).rejects.toBeInstanceOf(ApiError)

    expect(expiredEvents).toBe(1)
    expect(getToken()).toBeNull()
  })

  test('treats English token-error soft failure as a session expiry', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse(200, { status: false, message: 'token has expired' }))
    )

    await expect(api('/course/status/1')).rejects.toBeInstanceOf(ApiError)
    expect(expiredEvents).toBe(1)
    expect(getToken()).toBeNull()
  })

  test('does NOT treat a non-auth status:false body as expiry', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse(200, { status: false, message: '课程不存在' }))
    )

    await expect(api('/course/status/1')).rejects.toBeInstanceOf(ApiError)
    // Business error: token must be kept and no redirect fired.
    expect(expiredEvents).toBe(0)
    expect(getToken()).toBe('valid.jwt.token')
  })

  test('still treats a hard 401 with a token as expiry', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse(401, { message: 'Invalid token' }))
    )

    await expect(api('/course/status/1')).rejects.toBeInstanceOf(ApiError)
    expect(expiredEvents).toBe(1)
    expect(getToken()).toBeNull()
  })

  // Regression: a THIRD-PARTY platform 401 ("not logged into Zhihuishu/Chaoxing")
  // must NOT be treated as app-session expiry. It previously wiped the app token
  // and looped the user to /login the moment they opened the Zhihuishu page,
  // whose bootstrap fetches /course/zhihuishu/config (401 until Zhihuishu login).
  test('does NOT log out on a Zhihuishu "not logged in" 401', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse(401, { detail: 'Zhihuishu not logged in' }))
    )

    await expect(api('/course/zhihuishu/config')).rejects.toBeInstanceOf(ApiError)
    expect(expiredEvents).toBe(0)
    expect(getToken()).toBe('valid.jwt.token')
  })

  test('does NOT log out on a Chaoxing "please login first" 401', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse(401, { detail: 'Please login to Chaoxing first' }))
    )

    await expect(api('/course/chaoxing/courses')).rejects.toBeInstanceOf(ApiError)
    expect(expiredEvents).toBe(0)
    expect(getToken()).toBe('valid.jwt.token')
  })

  test('does NOT log out on a generic third-party "Login failed" 401', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse(401, { detail: 'Login failed' }))
    )

    await expect(api('/course/zhihuishu/password-login')).rejects.toBeInstanceOf(ApiError)
    expect(expiredEvents).toBe(0)
    expect(getToken()).toBe('valid.jwt.token')
  })
})
