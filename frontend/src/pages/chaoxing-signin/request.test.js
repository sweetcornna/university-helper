import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { fetchWithTimeout } from './request'

describe('Chaoxing request timeout', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  test('aborts a pending request at 20 seconds with a readable error', async () => {
    const abortError = new DOMException('The operation was aborted.', 'AbortError')
    let requestSignal
    const fetchMock = vi.fn((_input, options) => {
      requestSignal = options.signal
      return new Promise((_, reject) => {
        options.signal.addEventListener('abort', () => reject(abortError), { once: true })
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    const request = fetchWithTimeout('/api/v1/chaoxing/tasks')
    const timeoutAssertion = expect(request).rejects.toThrow('请求超时，请稍后重试。')

    await vi.advanceTimersByTimeAsync(19999)
    expect(requestSignal.aborted).toBe(false)
    expect(vi.getTimerCount()).toBe(1)

    await vi.advanceTimersByTimeAsync(1)

    await timeoutAssertion
    expect(requestSignal.aborted).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
  })

  test('clears the timeout after a normal response', async () => {
    let requestSignal
    const response = { ok: true, status: 200 }
    vi.stubGlobal(
      'fetch',
      vi.fn((_input, options) => {
        requestSignal = options.signal
        return Promise.resolve(response)
      })
    )

    await expect(fetchWithTimeout('/api/v1/chaoxing/tasks')).resolves.toBe(response)
    expect(requestSignal.aborted).toBe(false)
    expect(vi.getTimerCount()).toBe(0)

    await vi.advanceTimersByTimeAsync(20000)
    expect(requestSignal.aborted).toBe(false)
  })

  test('preserves a caller signal and its abort error', async () => {
    const controller = new AbortController()
    const abortError = new DOMException('Caller aborted the request.', 'AbortError')
    let requestSignal
    const fetchMock = vi.fn((_input, options) => {
      requestSignal = options.signal
      return new Promise((_, reject) => {
        options.signal.addEventListener('abort', () => reject(abortError), { once: true })
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    const request = fetchWithTimeout('/api/v1/chaoxing/tasks', {
      signal: controller.signal,
    })
    const abortAssertion = expect(request).rejects.toBe(abortError)

    expect(requestSignal).toBe(controller.signal)
    expect(vi.getTimerCount()).toBe(0)

    controller.abort()

    await abortAssertion
  })
})
