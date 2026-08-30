import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import ChaoxingSignin from './ChaoxingSignin'
import { ToastProvider } from '../components/Toast'
import { decodeQrCodeFromFile } from './chaoxing-signin/utils'

vi.mock('../components', async (importOriginal) => ({
  ...(await importOriginal()),
  useRuntimeProfile: () => ({ profile: 'local', isLocal: true, requiresAuth: false, loading: false }),
}))

vi.mock('./chaoxing-signin/utils', async (importOriginal) => ({
  ...(await importOriginal()),
  decodeQrCodeFromFile: vi.fn(),
}))

const createDeferred = () => {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

const createFile = (name) => new File(['image'], name, { type: 'image/png' })

const mockBootstrapResponse = (payload = {}) => ({
  ok: true,
  status: 200,
  text: async () => JSON.stringify(payload),
})

const waitFor = async (predicate) => {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const result = predicate()
    if (result) return result

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }

  throw new Error('Timed out waiting for the QR code form to render.')
}

describe('ChaoxingSignin QR upload race handling', () => {
  let container
  let root

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)

    vi.stubGlobal('fetch', vi.fn(async () => mockBootstrapResponse({ data: [] })))
    decodeQrCodeFromFile.mockReset()
  })

  afterEach(() => {
    if (root) {
      act(() => {
        root.unmount()
      })
    }
    container?.remove()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  const renderQrForm = async () => {
    await act(async () => {
      root.render(
        <ToastProvider>
          <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
            <ChaoxingSignin />
          </MemoryRouter>
        </ToastProvider>
      )
    })

    const signType = await waitFor(() => container.querySelector('#cx-signtype'))

    await act(async () => {
      signType.value = 'qrcode'
      signType.dispatchEvent(new Event('change', { bubbles: true }))
    })

    return waitFor(() => container.querySelector('#cx-qrcode-file'))
  }

  const chooseFile = async (input, file) => {
    Object.defineProperty(input, 'files', {
      configurable: true,
      value: [file],
    })

    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }))
    })
  }

  const settle = async (deferred, action) => {
    await act(async () => {
      action()
      await deferred.promise.catch(() => undefined)
    })
  }

  test('keeps the newer successful decode when the older decode succeeds later', async () => {
    const fileA = createFile('a.png')
    const fileB = createFile('b.png')
    const decodeA = createDeferred()
    const decodeB = createDeferred()
    decodeQrCodeFromFile.mockImplementation((file) =>
      file === fileA ? decodeA.promise : decodeB.promise
    )

    const input = await renderQrForm()
    await chooseFile(input, fileA)
    await chooseFile(input, fileB)

    await settle(decodeB, () => decodeB.resolve('decoded-b'))
    expect(container.querySelector('#cx-qrcode').value).toBe('decoded-b')
    expect(container.textContent).toContain('解码成功')

    await settle(decodeA, () => decodeA.resolve('decoded-a'))
    expect(container.querySelector('#cx-qrcode').value).toBe('decoded-b')
    expect(container.textContent).toContain('解码成功')
  })

  test('keeps the newer successful decode when the older decode fails later', async () => {
    const fileA = createFile('a.png')
    const fileB = createFile('b.png')
    const decodeA = createDeferred()
    const decodeB = createDeferred()
    decodeQrCodeFromFile.mockImplementation((file) =>
      file === fileA ? decodeA.promise : decodeB.promise
    )

    const input = await renderQrForm()
    await chooseFile(input, fileA)
    await chooseFile(input, fileB)

    await settle(decodeB, () => decodeB.resolve('decoded-b'))
    await settle(decodeA, () => decodeA.reject(new Error('old decode failed')))

    expect(container.querySelector('#cx-qrcode').value).toBe('decoded-b')
    expect(container.textContent).toContain('解码成功')
    expect(container.textContent).not.toContain('old decode failed')
  })

  test('keeps the current decode error when the newer decode fails', async () => {
    const fileA = createFile('a.png')
    const fileB = createFile('b.png')
    const decodeA = createDeferred()
    const decodeB = createDeferred()
    decodeQrCodeFromFile.mockImplementation((file) =>
      file === fileA ? decodeA.promise : decodeB.promise
    )

    const input = await renderQrForm()
    await chooseFile(input, fileA)
    await chooseFile(input, fileB)

    await settle(decodeB, () => decodeB.reject(new Error('current decode failed')))
    expect(container.querySelector('#cx-qrcode').value).toBe('')
    expect(container.textContent).toContain('current decode failed')

    await settle(decodeA, () => decodeA.resolve('stale decoded-a'))
    expect(container.querySelector('#cx-qrcode').value).toBe('')
    expect(container.textContent).toContain('current decode failed')
  })

  test('does not update state when a pending decode completes after unmount', async () => {
    const decodeA = createDeferred()
    decodeQrCodeFromFile.mockReturnValue(decodeA.promise)
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})

    const input = await renderQrForm()
    await chooseFile(input, createFile('a.png'))

    act(() => {
      root.unmount()
    })
    root = null

    await settle(decodeA, () => decodeA.resolve('decoded-a'))
    expect(consoleError).not.toHaveBeenCalled()
  })
})
