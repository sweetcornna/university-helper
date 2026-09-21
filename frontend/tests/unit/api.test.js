import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api } from '../../src/utils/api'
import * as auth from '../../src/utils/auth'

describe('api', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    globalThis.fetch = vi.fn()
  })

  const mockFetchResponse = (body, { ok = true, status = 200 } = {}) => {
    globalThis.fetch.mockResolvedValue({
      ok,
      status,
      text: () => Promise.resolve(JSON.stringify(body)),
    })
  }

  it('returns parsed data on successful request', async () => {
    const data = { id: 1, name: 'test' }
    mockFetchResponse(data)

    const result = await api('/users')

    expect(result).toEqual(data)
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
    expect(globalThis.fetch.mock.calls[0][0]).toContain('/users')
  })

  it('throws timeout error when request is aborted', async () => {
    globalThis.fetch.mockImplementation(() => {
      const error = new DOMException('The operation was aborted.', 'AbortError')
      return Promise.reject(error)
    })

    await expect(api('/slow', { timeoutMs: 1 })).rejects.toThrow(
      '请求超时，请稍后重试。'
    )
  })

  it('extracts error message from server error response', async () => {
    mockFetchResponse({ message: '用户名或密码错误' }, { ok: false, status: 401 })

    await expect(api('/auth/login')).rejects.toThrow('用户名或密码错误')
  })

  it('extracts detail field from error response', async () => {
    mockFetchResponse({ detail: 'Not found' }, { ok: false, status: 404 })

    await expect(api('/missing')).rejects.toThrow('Not found')
  })

  it('falls back to status code message when no error field present', async () => {
    mockFetchResponse({}, { ok: false, status: 404 })

    await expect(api('/broken')).rejects.toThrow('请求失败（404）')
  })

  it('uses readable guidance for a 5xx without a specific message', async () => {
    mockFetchResponse({}, { ok: false, status: 500 })

    await expect(api('/broken')).rejects.toThrow('服务器出错了（500）')
  })

  it('attaches Authorization header when token exists', async () => {
    vi.spyOn(auth, 'getToken').mockReturnValue('my-jwt-token')
    mockFetchResponse({ ok: true })

    await api('/protected')

    const requestOptions = globalThis.fetch.mock.calls[0][1]
    expect(requestOptions.headers.Authorization).toBe('Bearer my-jwt-token')
  })

  it('does not attach Authorization header when no token', async () => {
    vi.spyOn(auth, 'getToken').mockReturnValue(null)
    mockFetchResponse({ ok: true })

    await api('/public')

    const requestOptions = globalThis.fetch.mock.calls[0][1]
    expect(requestOptions.headers).not.toHaveProperty('Authorization')
  })
})
