import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import RuntimeProfileProvider from './RuntimeProfileProvider'
import { useRuntimeProfile } from './runtimeProfileContext'

function Probe() {
  const { profile, isLocal, loading } = useRuntimeProfile()
  return <p>{loading ? 'loading' : `${profile}:${isLocal}`}</p>
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('RuntimeProfileProvider', () => {
  test('enables local capabilities only for an explicit local response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ profile: 'local', requires_auth: false }),
      }),
    )

    render(
      <RuntimeProfileProvider>
        <Probe />
      </RuntimeProfileProvider>,
    )

    expect(await screen.findByText('local:true')).toBeTruthy()
  })

  test('fails closed to server mode when capability discovery fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))

    render(
      <RuntimeProfileProvider>
        <Probe />
      </RuntimeProfileProvider>,
    )

    await waitFor(() => expect(screen.getByText('server:false')).toBeTruthy())
  })

  test('fails closed at the capability deadline when fetch never settles', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn(() => new Promise(() => {}))
    vi.stubGlobal('fetch', fetchMock)

    render(
      <RuntimeProfileProvider>
        <Probe />
      </RuntimeProfileProvider>,
    )

    expect(screen.getByText('loading')).toBeTruthy()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(19_999)
    })
    expect(screen.getByText('loading')).toBeTruthy()
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(false)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(screen.getByText('server:false')).toBeTruthy()
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
  })

  test('aborts the capability request and clears its deadline on unmount', () => {
    vi.useFakeTimers()
    let requestSignal
    vi.stubGlobal(
      'fetch',
      vi.fn((_input, options) => {
        requestSignal = options.signal
        return new Promise(() => {})
      }),
    )

    const { unmount } = render(
      <RuntimeProfileProvider>
        <Probe />
      </RuntimeProfileProvider>,
    )

    expect(vi.getTimerCount()).toBe(1)
    unmount()

    expect(requestSignal.aborted).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
  })
})
