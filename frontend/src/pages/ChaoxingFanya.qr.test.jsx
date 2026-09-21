import { act } from 'react-dom/test-utils'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import ChaoxingFanya from './ChaoxingFanya'

// Regression guard for a wiring bug: the 泛雅 page handed its generic `callApi`
// (which prefixes only `/api/v1`) to the QR panel, so the request went to
// `/api/v1/qr-login` — a 405 — and the panel sat on 暂无二维码 forever. The panel
// needs a request scoped to the **Chaoxing** API root, which is what
// `callChaoxingApi` wraps. Asserting the full URL is the only way to catch it:
// a mocked requester in a component test cannot.
const jsonResponse = (payload) => ({
  ok: true,
  status: 200,
  text: async () => JSON.stringify(payload),
})

const waitFor = async (predicate, timeoutMs = 2000) => {
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    const result = predicate()
    if (result) return result
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
  throw new Error(
    `Timed out waiting for the page to settle. Rendered text: ${document.body.textContent?.slice(0, 400)}`
  )
}

describe('ChaoxingFanya QR login wiring', () => {
  let container
  let root
  let fetchMock

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    window.sessionStorage.setItem('auth_token', 'demo-token')
    window.localStorage.clear()

    fetchMock = vi.fn(async (input) => {
      const url = String(input)
      if (url.includes('/api/v1/chaoxing/session')) {
        return jsonResponse({ active: false, username: null, expires_at: null })
      }
      if (url.includes('/api/v1/chaoxing/qr-login')) {
        return jsonResponse({ session_id: 's1', status: 'pending', qr_code: 'BASE64PNG' })
      }
      if (url.includes('/course/chaoxing/preferences')) {
        return jsonResponse({ status: 'success', preferences: {}, has_answer_bank: false })
      }
      return jsonResponse({ status: true, data: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.unstubAllGlobals()
  })

  test('requests the QR from the Chaoxing-scoped URL', async () => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <ChaoxingFanya />
        </MemoryRouter>
      )
    })

    const qrTab = await waitFor(() =>
      Array.from(container.querySelectorAll('[role="tab"]')).find((tab) =>
        tab.textContent?.includes('扫码登录')
      )
    )

    await act(async () => {
      qrTab.click()
    })

    await waitFor(() =>
      fetchMock.mock.calls.some(([url]) => String(url).includes('/chaoxing/qr-login'))
    )

    const urls = fetchMock.mock.calls.map(([url]) => String(url))
    // The exact bug: the unprefixed path is a 405 on the real server.
    expect(urls.some((url) => url.includes('/api/v1/qr-login'))).toBe(false)
    expect(urls.some((url) => url.includes('/api/v1/chaoxing/qr-login'))).toBe(true)
  })
})
