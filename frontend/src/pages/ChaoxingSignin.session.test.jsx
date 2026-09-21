import { act } from 'react-dom/test-utils'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { ToastProvider } from '../components'
import ChaoxingSignin from './ChaoxingSignin'
import { QR_POLL_INTERVAL_MS } from './chaoxing-shared/utils'

// The reported bug: log in on 泛雅, switch to 签到, and the page still demands
// the password. The 签到 page never asked the server whether a session existed,
// so these tests pin the two halves of the fix:
//   * with a server-held session the action runs without a password;
//   * without one it is still blocked, exactly as before.
//
// They assert on whether the request went out rather than on the toast copy,
// because "did the action proceed" is the behaviour that was broken.

const jsonResponse = (payload) => ({
  ok: true,
  status: 200,
  text: async () => JSON.stringify(payload),
})

const SESSION_ACTIVE = {
  active: true,
  username: 'student01',
  expires_at: '2026-10-01T00:00:00+00:00',
}

const SESSION_ABSENT = { active: false, username: null, expires_at: null }

const waitFor = async (predicate, timeoutMs = 1500) => {
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    const result = predicate()
    if (result) return result
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
  throw new Error(
    `Timed out waiting for the page to settle. Rendered text: ${document.body.textContent?.slice(0, 600)}`
  )
}

const findButton = (container, label) =>
  Array.from(container.querySelectorAll('button')).find((button) =>
    button.textContent?.includes(label)
  )

const calledWith = (fetchMock, fragment) =>
  fetchMock.mock.calls.some(([url]) => String(url).includes(fragment))

describe('ChaoxingSignin shared session', () => {
  let container
  let root
  let fetchMock

  /** Stubs fetch. `onSign`/`onQrStart` let a test override a single endpoint. */
  const stubFetch = (sessionPayload, overrides = {}) => {
    fetchMock = vi.fn(async (input, options = {}) => {
      const url = String(input)
      const method = String(options.method || 'GET').toUpperCase()

      for (const [fragment, responder] of Object.entries(overrides)) {
        if (url.includes(fragment)) return responder(method, url, options)
      }
      if (url.includes('/api/v1/chaoxing/session')) return jsonResponse(sessionPayload)
      if (url.includes('/api/v1/chaoxing/sign'))
        return jsonResponse({ status: true, message: '签到成功。' })
      // Everything else: an empty but well-formed payload, so the page settles
      // without pretending to have data.
      return jsonResponse({ status: true, data: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
  }

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    window.sessionStorage.setItem('auth_token', 'demo-token')
    window.localStorage.clear()
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.unstubAllGlobals()
  })

  const render = async () => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <ToastProvider>
            <ChaoxingSignin />
          </ToastProvider>
        </MemoryRouter>
      )
    })
    await waitFor(() => findButton(container, '课程签到'))
  }

  test('hides the password field when the server holds a session', async () => {
    stubFetch(SESSION_ACTIVE)
    await render()

    expect(container.querySelector('#cx-password')).toBeNull()
    // The account is adopted from the session rather than retyped.
    expect(container.querySelector('#cx-username').value).toBe('student01')
    expect(container.textContent).toContain('已登录学习通账号')
  })

  test('runs a sign-in without a password when a session exists', async () => {
    stubFetch(SESSION_ACTIVE)
    await render()

    act(() => {
      findButton(container, '课程签到').click()
    })

    // The request going out at all is the fix: it used to be rejected before
    // reaching the backend with 「请输入账号和密码」.
    await waitFor(() => calledWith(fetchMock, '/chaoxing/sign'))
  })

  test('still blocks a sign-in with no session and no password', async () => {
    stubFetch(SESSION_ABSENT)
    await render()

    expect(container.querySelector('#cx-password')).not.toBeNull()
    expect(container.textContent).not.toContain('已登录学习通账号')

    act(() => {
      findButton(container, '课程签到').click()
    })

    // Give the (rejected) flow a chance to run before asserting it did not.
    await waitFor(() => document.body.textContent?.includes('请输入账号和密码'))
    expect(calledWith(fetchMock, '/chaoxing/sign')).toBe(false)
  })

  test('offers 扫码登录 as an alternative to the password form', async () => {
    stubFetch(SESSION_ABSENT, {
      '/chaoxing/qr-login': () =>
        jsonResponse({ session_id: 's1', status: 'pending', qr_code: 'BASE64PNG' }),
    })
    await render()

    act(() => {
      findButton(container, '扫码登录').click()
    })

    const img = await waitFor(() => container.querySelector('img[alt="学习通登录二维码"]'))
    expect(img.getAttribute('src')).toBe('data:image/png;base64,BASE64PNG')
    expect(calledWith(fetchMock, '/chaoxing/qr-login')).toBe(true)
  })

  test('a confirmed scan marks the page logged in', async () => {
    // Fake only the interval APIs so React's scheduler still runs; this lets
    // the test drive the panel's poll without waiting 2 real seconds.
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    try {
      stubFetch(SESSION_ABSENT, {
        '/chaoxing/qr-login': (method) => {
          if (method === 'POST') {
            return jsonResponse({ session_id: 's1', status: 'pending', qr_code: 'BASE64PNG' })
          }
          return jsonResponse({ session_id: 's1', status: 'success', username: 'student01' })
        },
      })
      await render()

      act(() => {
        findButton(container, '扫码登录').click()
      })
      await waitFor(() => container.querySelector('img[alt="学习通登录二维码"]'))

      await act(async () => {
        await vi.advanceTimersByTimeAsync(QR_POLL_INTERVAL_MS)
      })

      await waitFor(() => container.textContent?.includes('已登录学习通账号'))
      expect(container.textContent).toContain('student01')
    } finally {
      vi.useRealTimers()
    }
  })

  test('offers 切换账号 once logged in, and returns to the form', async () => {
    const sessionPayload = { ...SESSION_ACTIVE }
    stubFetch(SESSION_ACTIVE, {
      '/api/v1/chaoxing/session': (method) => {
        if (method === 'DELETE') {
          Object.assign(sessionPayload, SESSION_ABSENT)
          return jsonResponse({ status: 'success' })
        }
        return jsonResponse(sessionPayload)
      },
    })
    await render()

    act(() => {
      findButton(container, '切换账号').click()
    })

    await waitFor(() => container.querySelector('#cx-password'))
    expect(container.textContent).not.toContain('已登录学习通账号')
  })
})
