import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

const { maps, mapFactory, markerFactory, tileLayerFactory } = vi.hoisted(() => {
  const maps = []
  const mapFactory = vi.fn(() => {
    const map = {
      invalidateSize: vi.fn(),
      on: vi.fn(),
      panTo: vi.fn(),
      remove: vi.fn(),
      setView: vi.fn(),
    }
    map.setView.mockReturnValue(map)
    maps.push(map)
    return map
  })
  const markerFactory = vi.fn(() => {
    const marker = {
      addTo: vi.fn(),
      setLatLng: vi.fn(),
    }
    marker.addTo.mockReturnValue(marker)
    return marker
  })
  const tileLayerFactory = vi.fn(() => ({ addTo: vi.fn() }))
  return { maps, mapFactory, markerFactory, tileLayerFactory }
})

vi.mock('leaflet', () => {
  const leaflet = {
    Icon: {
      Default: {
        mergeOptions: vi.fn(),
        prototype: {},
      },
    },
    map: mapFactory,
    marker: markerFactory,
    tileLayer: tileLayerFactory,
  }
  return { default: leaflet }
})

import BaiduMapPickerModal from './BaiduMapPickerModal'

const props = {
  initialLocation: null,
  onClose: vi.fn(),
  onConfirm: vi.fn(),
}

const deferred = () => {
  let resolve
  let reject
  const promise = new Promise((promiseResolve, promiseReject) => {
    resolve = promiseResolve
    reject = promiseReject
  })
  return { promise, resolve, reject }
}

const jsonResponse = (payload) => ({
  ok: true,
  json: () => Promise.resolve(payload),
})

const flushPromises = async () => {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

describe('BaiduMapPickerModal map lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn())
    maps.length = 0
    mapFactory.mockClear()
    markerFactory.mockClear()
    tileLayerFactory.mockClear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  test('cleans up the map and pending resize timer when unmounted while open', () => {
    const { unmount } = render(<BaiduMapPickerModal {...props} open />)
    const map = maps[0]

    act(() => {
      vi.advanceTimersByTime(99)
      unmount()
    })
    act(() => {
      vi.advanceTimersByTime(1)
    })

    expect(map.invalidateSize).not.toHaveBeenCalled()
    expect(map.remove).toHaveBeenCalledTimes(1)
  })

  test('removes once on close and creates a fresh map when reopened', () => {
    const view = render(<BaiduMapPickerModal {...props} open />)
    const firstMap = maps[0]

    view.rerender(<BaiduMapPickerModal {...props} open={false} />)
    expect(firstMap.remove).toHaveBeenCalledTimes(1)

    view.rerender(<BaiduMapPickerModal {...props} open />)
    const secondMap = maps[1]
    expect(mapFactory).toHaveBeenCalledTimes(2)
    expect(secondMap).not.toBe(firstMap)

    view.rerender(<BaiduMapPickerModal {...props} open={false} />)
    expect(firstMap.remove).toHaveBeenCalledTimes(1)
    expect(secondMap.remove).toHaveBeenCalledTimes(1)
  })

  test('keeps reverse-geocode loading and address tied to the latest map click', async () => {
    const first = deferred()
    const second = deferred()
    globalThis.fetch.mockImplementation((url) => {
      if (url.includes('lat=10&lng=20')) return first.promise
      if (url.includes('lat=30&lng=40')) return second.promise
      throw new Error(`Unexpected URL: ${url}`)
    })

    render(<BaiduMapPickerModal {...props} open />)
    const clickHandler = maps[0].on.mock.calls.find(
      ([eventName]) => eventName === 'click'
    )[1]

    act(() => {
      clickHandler({ latlng: { lat: 10, lng: 20 } })
    })
    act(() => {
      clickHandler({ latlng: { lat: 30, lng: 40 } })
    })

    expect(screen.getByText('解析地址中...')).toBeInTheDocument()

    await act(async () => {
      first.resolve(jsonResponse({ data: { address: '旧地址' } }))
      await flushPromises()
    })
    expect(screen.getByText('解析地址中...')).toBeInTheDocument()
    expect(screen.queryByText('旧地址')).not.toBeInTheDocument()

    await act(async () => {
      second.resolve(jsonResponse({ data: { address: '新地址' } }))
      await flushPromises()
    })
    expect(screen.getByText('新地址')).toBeInTheDocument()
    expect(screen.queryByText('解析地址中...')).not.toBeInTheDocument()
  })

  test('times out a never-settling reverse geocode and clears its loading state', async () => {
    let requestSignal
    globalThis.fetch.mockImplementation((_url, options) => {
      requestSignal = options.signal
      return new Promise(() => {})
    })

    render(<BaiduMapPickerModal {...props} open />)
    const clickHandler = maps[0].on.mock.calls.find(
      ([eventName]) => eventName === 'click'
    )[1]
    act(() => {
      clickHandler({ latlng: { lat: 10, lng: 20 } })
      vi.advanceTimersByTime(100)
    })

    expect(screen.getByText('解析地址中...')).toBeInTheDocument()
    expect(vi.getTimerCount()).toBe(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000)
      await flushPromises()
    })

    expect(requestSignal.aborted).toBe(true)
    expect(screen.getByText('未解析到详细地址')).toBeInTheDocument()
    expect(screen.queryByText('解析地址中...')).not.toBeInTheDocument()
    expect(vi.getTimerCount()).toBe(0)
  })

  test('times out a never-settling place search and clears its loading state', async () => {
    let requestSignal
    globalThis.fetch.mockImplementation((_url, options) => {
      requestSignal = options.signal
      return new Promise(() => {})
    })

    render(<BaiduMapPickerModal {...props} open />)
    const input = screen.getByPlaceholderText('搜索地点名称...')
    fireEvent.change(input, { target: { value: '地点' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    act(() => {
      vi.advanceTimersByTime(100)
    })

    expect(input.nextElementSibling).toBeDisabled()
    expect(vi.getTimerCount()).toBe(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000)
      await flushPromises()
    })

    expect(requestSignal.aborted).toBe(true)
    expect(screen.getByText('搜索失败，请稍后重试')).toBeInTheDocument()
    expect(input.nextElementSibling).not.toBeDisabled()
    expect(vi.getTimerCount()).toBe(0)
  })

  test('ignores an old search after close and keeps the new modal loading state', async () => {
    const first = deferred()
    const second = deferred()
    globalThis.fetch.mockImplementation((url) => {
      if (url.includes('query=%E6%90%9C%E7%B4%A2A')) return first.promise
      if (url.includes('query=%E6%90%9C%E7%B4%A2B')) return second.promise
      throw new Error(`Unexpected URL: ${url}`)
    })

    const view = render(<BaiduMapPickerModal {...props} open />)
    const input = screen.getByPlaceholderText('搜索地点名称...')
    fireEvent.change(input, { target: { value: '搜索A' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    view.rerender(<BaiduMapPickerModal {...props} open={false} />)
    view.rerender(<BaiduMapPickerModal {...props} open />)
    const reopenedInput = screen.getByPlaceholderText('搜索地点名称...')
    fireEvent.change(reopenedInput, { target: { value: '搜索B' } })
    fireEvent.keyDown(reopenedInput, { key: 'Enter' })

    const searchButton = reopenedInput.nextElementSibling
    expect(searchButton).toBeDisabled()

    await act(async () => {
      first.resolve(
        jsonResponse({
          data: {
            results: [{ id: 'a', name: '旧结果', address: '旧地址' }],
          },
        })
      )
      await flushPromises()
    })
    expect(searchButton).toBeDisabled()
    expect(screen.queryByText('旧结果')).not.toBeInTheDocument()

    await act(async () => {
      second.resolve(
        jsonResponse({
          data: {
            results: [{ id: 'b', name: '新结果', address: '新地址' }],
          },
        })
      )
      await flushPromises()
    })
    expect(screen.getByText('新结果')).toBeInTheDocument()
    expect(searchButton).not.toBeDisabled()
  })

  test('accepts immediate requests after reopen without adopting closed results', async () => {
    const oldReverse = deferred()
    const oldSearch = deferred()
    const newReverse = deferred()
    const newSearch = deferred()
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    globalThis.fetch.mockImplementation((url) => {
      if (url.includes('lat=10&lng=20')) return oldReverse.promise
      if (url.includes('lat=30&lng=40')) return newReverse.promise
      if (url.includes('query=%E6%97%A7%E5%9C%B0%E7%82%B9')) return oldSearch.promise
      if (url.includes('query=%E6%96%B0%E5%9C%B0%E7%82%B9')) return newSearch.promise
      throw new Error(`Unexpected URL: ${url}`)
    })

    const view = render(<BaiduMapPickerModal {...props} open />)
    const firstClickHandler = maps[0].on.mock.calls.find(
      ([eventName]) => eventName === 'click'
    )[1]
    act(() => {
      firstClickHandler({ latlng: { lat: 10, lng: 20 } })
    })
    const firstInput = screen.getByPlaceholderText('搜索地点名称...')
    fireEvent.change(firstInput, { target: { value: '旧地点' } })
    fireEvent.keyDown(firstInput, { key: 'Enter' })
    act(() => {
      vi.advanceTimersByTime(100)
    })

    view.rerender(<BaiduMapPickerModal {...props} open={false} />)
    expect(vi.getTimerCount()).toBe(0)

    view.rerender(<BaiduMapPickerModal {...props} open />)
    const secondClickHandler = maps[1].on.mock.calls.find(
      ([eventName]) => eventName === 'click'
    )[1]
    act(() => {
      secondClickHandler({ latlng: { lat: 30, lng: 40 } })
    })
    const secondInput = screen.getByPlaceholderText('搜索地点名称...')
    fireEvent.change(secondInput, { target: { value: '新地点' } })
    fireEvent.keyDown(secondInput, { key: 'Enter' })
    expect(globalThis.fetch).toHaveBeenCalledTimes(4)

    act(() => {
      vi.advanceTimersByTime(100)
    })

    await act(async () => {
      oldReverse.resolve(jsonResponse({ data: { address: '关闭后旧地址' } }))
      oldSearch.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            data: { results: [{ id: 'old', name: '关闭后旧结果' }] },
          }),
      })
      await flushPromises()
    })
    expect(screen.queryByText('关闭后旧地址')).not.toBeInTheDocument()
    expect(screen.queryByText('关闭后旧结果')).not.toBeInTheDocument()

    await act(async () => {
      newReverse.resolve(jsonResponse({ data: { address: '重开后新地址' } }))
      newSearch.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            data: { results: [{ id: 'new', name: '重开后新结果' }] },
          }),
      })
      await flushPromises()
    })
    expect(screen.getByText('重开后新地址')).toBeInTheDocument()
    expect(screen.getByText('重开后新结果')).toBeInTheDocument()
    expect(secondInput.nextElementSibling).not.toBeDisabled()
    expect(vi.getTimerCount()).toBe(0)
    expect(errorSpy).not.toHaveBeenCalled()
  })

  test('does not submit a second search while the first one is loading', async () => {
    const pending = deferred()
    globalThis.fetch.mockReturnValue(pending.promise)

    render(<BaiduMapPickerModal {...props} open />)
    const input = screen.getByPlaceholderText('搜索地点名称...')
    fireEvent.change(input, { target: { value: '地点' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(globalThis.fetch).toHaveBeenCalledTimes(1)

    await act(async () => {
      pending.resolve(jsonResponse({ data: { results: [] } }))
      await flushPromises()
    })
  })

  test('does not write async results after the modal closes', async () => {
    const reverse = deferred()
    const search = deferred()
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    globalThis.fetch.mockImplementation((url) =>
      url.includes('/reverse-geocode') ? reverse.promise : search.promise
    )

    const view = render(<BaiduMapPickerModal {...props} open />)
    const clickHandler = maps[0].on.mock.calls.find(
      ([eventName]) => eventName === 'click'
    )[1]
    act(() => {
      clickHandler({ latlng: { lat: 10, lng: 20 } })
    })

    const input = screen.getByPlaceholderText('搜索地点名称...')
    fireEvent.change(input, { target: { value: '地点' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    act(() => {
      vi.advanceTimersByTime(100)
    })
    expect(vi.getTimerCount()).toBe(2)
    view.rerender(<BaiduMapPickerModal {...props} open={false} />)
    expect(vi.getTimerCount()).toBe(0)

    await act(async () => {
      reverse.resolve(jsonResponse({ data: { address: '关闭后地址' } }))
      search.resolve(
        jsonResponse({
          data: {
            results: [{ id: 'closed', name: '关闭后结果' }],
          },
        })
      )
      await flushPromises()
    })

    expect(errorSpy).not.toHaveBeenCalled()
    expect(screen.queryByText('关闭后地址')).not.toBeInTheDocument()
    expect(screen.queryByText('关闭后结果')).not.toBeInTheDocument()
  })
})
