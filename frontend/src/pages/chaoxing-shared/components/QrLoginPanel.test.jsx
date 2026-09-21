import { act } from 'react-dom/test-utils'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import QrLoginPanel from './QrLoginPanel'
import { QR_POLL_INTERVAL_MS } from '../utils'

// Only the interval APIs are faked, so React's own scheduler (which uses
// setTimeout / MessageChannel) keeps running and `act` can still flush.
const useIntervalTimers = () => vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })

const advance = async (ms) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe('QrLoginPanel', () => {
  let container
  let root

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    useIntervalTimers()
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.useRealTimers()
  })

  const renderPanel = async (request, onSuccess = vi.fn()) => {
    await act(async () => {
      root.render(<QrLoginPanel chaoxingRequest={request} onSuccess={onSuccess} />)
    })
    return onSuccess
  }

  test('renders the QR image the server returned', async () => {
    const request = vi.fn(async () => ({
      session_id: 's1',
      qr_code: 'BASE64PNG',
      status: 'pending',
    }))

    await renderPanel(request)

    const img = container.querySelector('img')
    expect(img).not.toBeNull()
    expect(img.getAttribute('src')).toBe('data:image/png;base64,BASE64PNG')
    // It fetches a code on mount rather than waiting for another click.
    expect(request).toHaveBeenCalledWith('/qr-login', { method: 'POST' })
  })

  test('reports a failure to mint a code without rendering a broken image', async () => {
    const request = vi.fn(async () => {
      throw new Error('无法生成二维码')
    })

    await renderPanel(request)

    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).toContain('无法生成二维码')
  })

  test('polls until the phone confirms, then stops', async () => {
    const request = vi.fn(async (path) => {
      if (path === '/qr-login') return { session_id: 's1', qr_code: 'IMG', status: 'pending' }
      return { session_id: 's1', status: 'success', username: 'student01' }
    })

    const onSuccess = await renderPanel(request)

    await advance(QR_POLL_INTERVAL_MS)

    expect(onSuccess).toHaveBeenCalledTimes(1)
    expect(onSuccess.mock.calls[0][0].username).toBe('student01')

    // Terminal: no further polling once the session exists.
    const settled = request.mock.calls.length
    await advance(QR_POLL_INTERVAL_MS * 3)
    expect(request.mock.calls.length).toBe(settled)
  })

  test('keeps polling after a scan, because confirming is a separate step', async () => {
    let polls = 0
    const request = vi.fn(async (path) => {
      if (path === '/qr-login') return { session_id: 's1', qr_code: 'IMG', status: 'pending' }
      polls += 1
      return polls === 1
        ? { session_id: 's1', status: 'scanned', message: '已扫码，请在手机上确认' }
        : { session_id: 's1', status: 'success', username: 'student01' }
    })

    const onSuccess = await renderPanel(request)

    await advance(QR_POLL_INTERVAL_MS)
    expect(container.textContent).toContain('已扫码')
    expect(onSuccess).not.toHaveBeenCalled()

    await advance(QR_POLL_INTERVAL_MS)
    expect(onSuccess).toHaveBeenCalledTimes(1)
  })

  test('stops polling when the server reports the session failed', async () => {
    const request = vi.fn(async (path) => {
      if (path === '/qr-login') return { session_id: 's1', qr_code: 'IMG', status: 'pending' }
      return { session_id: 's1', status: 'failed', message: '二维码已过期' }
    })

    await renderPanel(request)

    await advance(QR_POLL_INTERVAL_MS)
    expect(container.textContent).toContain('二维码已过期')

    const settled = request.mock.calls.length
    await advance(QR_POLL_INTERVAL_MS * 3)
    expect(request.mock.calls.length).toBe(settled)
  })

  test('stops polling when the status request itself errors', async () => {
    const request = vi.fn(async (path) => {
      if (path === '/qr-login') return { session_id: 's1', qr_code: 'IMG', status: 'pending' }
      throw new Error('网络异常')
    })

    await renderPanel(request)

    await advance(QR_POLL_INTERVAL_MS)
    const settled = request.mock.calls.length
    await advance(QR_POLL_INTERVAL_MS * 3)
    expect(request.mock.calls.length).toBe(settled)
    expect(container.textContent).toContain('网络异常')
  })

  test('renders the refreshed image when the server replaces an expired code', async () => {
    let polls = 0
    const request = vi.fn(async (path) => {
      if (path === '/qr-login') return { session_id: 's1', qr_code: 'OLD', status: 'pending' }
      polls += 1
      if (polls === 1) {
        return {
          session_id: 's1',
          status: 'pending',
          qr_code: 'NEW',
          message: '二维码已过期，已为你刷新',
        }
      }
      return { session_id: 's1', status: 'pending' }
    })

    await renderPanel(request)
    expect(container.querySelector('img').getAttribute('src')).toBe('data:image/png;base64,OLD')

    await advance(QR_POLL_INTERVAL_MS)
    expect(container.querySelector('img').getAttribute('src')).toBe('data:image/png;base64,NEW')
    expect(container.textContent).toContain('二维码已过期，已为你刷新')
  })

  test('cancels the server-side session when the panel unmounts', async () => {
    const request = vi.fn(async () => ({ session_id: 's1', qr_code: 'IMG', status: 'pending' }))

    await renderPanel(request)
    act(() => root.unmount())

    expect(request).toHaveBeenCalledWith('/qr-login/s1', { method: 'DELETE' })
    // Re-create so afterEach's unmount has something to tear down.
    root = createRoot(container)
  })
})
