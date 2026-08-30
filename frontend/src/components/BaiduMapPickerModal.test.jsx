import { act, render } from '@testing-library/react'
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
  const markerFactory = vi.fn()
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

describe('BaiduMapPickerModal map lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    maps.length = 0
    mapFactory.mockClear()
    markerFactory.mockClear()
    tileLayerFactory.mockClear()
  })

  afterEach(() => {
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
})
