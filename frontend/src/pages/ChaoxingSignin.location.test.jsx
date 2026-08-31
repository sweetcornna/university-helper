import { act } from 'react-dom/test-utils'
import { createRoot } from 'react-dom/client'
import { fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import ChaoxingSignin from './ChaoxingSignin'
import { wgs84ToBd09 } from '../utils/coordTransform'

vi.mock('../components/BaiduMapPickerModal', () => ({
  default: ({ onConfirm }) => (
    <button
      type="button"
      data-testid="mock-map-confirm"
      onClick={() => onConfirm({ address: '地图地点', latitude: 31.2304, longitude: 121.4737 })}
    >
      确认地图坐标
    </button>
  ),
}))

const expectedBd09 = (wgsLat, wgsLng) => {
  const [bdLng, bdLat] = wgs84ToBd09(wgsLng, wgsLat)
  return { lat: String(bdLat), lng: String(bdLng) }
}

const mockBootstrapResponse = (payload = {}) => ({
  ok: true,
  status: 200,
  text: async () => JSON.stringify(payload),
})

const mockGeocodeResponse = {
  ok: true,
  status: 200,
  text: async () =>
    JSON.stringify({
      result: {
        formatted_address: '北京市朝阳区',
        location: { lat: 39.9042, lng: 116.4074 },
      },
    }),
}

const mockPlaceSearchResponse = {
  ok: true,
  status: 200,
  text: async () =>
    JSON.stringify({
      results: [
        {
          uid: 'place-1',
          name: '北京大学',
          city: '北京市',
          district: '海淀区',
          address: '颐和园路5号',
          location: { lat: 39.9928, lng: 116.3055 },
        },
      ],
    }),
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

const renderSignin = async (container, root) => {
  await act(async () => {
    root.render(
      <RuntimeProfileContext.Provider value={{ profile: 'server', isLocal: false, requiresAuth: true, loading: false }}>
        <ToastProvider>
          <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
            <ChaoxingSignin />
          </MemoryRouter>
        </ToastProvider>
      </RuntimeProfileContext.Provider>
    )
  })
}

const chooseLocationSignType = (container) => {
  const signType = container.querySelector('#cx-signtype')
  if (!signType) {
    throw new Error('Expected the Chaoxing sign-in form to render a sign type selector.')
  }
  act(() => {
    signType.value = 'location'
    signType.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

const setInputValue = (input, value) => {
  act(() => {
    fireEvent.change(input, { target: { value } })
  })
}

const waitFor = async (predicate, timeoutMs = 1000) => {
  const startedAt = Date.now()

  while (Date.now() - startedAt < timeoutMs) {
    const result = predicate()
    if (result) return result

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }

  throw new Error('Timed out waiting for location fields to update.')
}

describe('ChaoxingSignin location flow', () => {
  let container
  let root

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)

    window.sessionStorage.setItem('auth_token', 'demo-token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input) => {
        const url = String(input)

        if (url.includes('/api/v1/chaoxing/location/search')) {
          return mockPlaceSearchResponse
        }

        if (url.includes('/api/v1/chaoxing/location/geocode')) {
          return mockGeocodeResponse
        }

        return mockBootstrapResponse({ data: [] })
      })
    )
  })

  afterEach(() => {
    act(() => {
      root.unmount()
    })
    container.remove()
  })

  test('fills latitude and longitude after resolving an address', async () => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <ChaoxingSignin />
        </MemoryRouter>
      )
    })

    const signType = container.querySelector('#cx-signtype')
    if (!signType) {
      throw new Error('Expected the Chaoxing sign-in form to render a sign type selector.')
    }

    act(() => {
      signType.value = 'location'
      signType.dispatchEvent(new Event('change', { bubbles: true }))
    })

    const addressInput = container.querySelector('#cx-address')
    if (!addressInput) {
      throw new Error('Expected the location form to render an address field.')
    }

    act(() => {
      addressInput.value = '北京市朝阳区'
      addressInput.dispatchEvent(new Event('input', { bubbles: true }))
      addressInput.dispatchEvent(new Event('change', { bubbles: true }))
    })

    const resolveButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('解析坐标')
    )
    if (!resolveButton) {
      throw new Error('Expected a "解析坐标" button for address resolution.')
    }

    act(() => {
      resolveButton.click()
    })

    await waitFor(() => {
      const latitudeInput = container.querySelector('#cx-latitude')
      const longitudeInput = container.querySelector('#cx-longitude')

      if (!latitudeInput || !longitudeInput) return false
      const { lat, lng } = expectedBd09(39.9042, 116.4074)
      if (latitudeInput.value !== lat) return false
      if (longitudeInput.value !== lng) return false

      return true
    })
  })

  test('lets the user search a place and pick a result', async () => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <ChaoxingSignin />
        </MemoryRouter>
      )
    })

    const signType = container.querySelector('#cx-signtype')
    if (!signType) {
      throw new Error('Expected the Chaoxing sign-in form to render a sign type selector.')
    }

    act(() => {
      signType.value = 'location'
      signType.dispatchEvent(new Event('change', { bubbles: true }))
    })

    const addressInput = container.querySelector('#cx-address')
    if (!addressInput) {
      throw new Error('Expected the location form to render an address field.')
    }

    act(() => {
      addressInput.value = '北京大学'
      addressInput.dispatchEvent(new Event('input', { bubbles: true }))
      addressInput.dispatchEvent(new Event('change', { bubbles: true }))
    })

    const searchButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('搜索地点')
    )
    if (!searchButton) {
      throw new Error('Expected a "搜索地点" button for place search.')
    }

    act(() => {
      searchButton.click()
    })

    await waitFor(() => container.textContent?.includes('北京大学'))

    const resultButton = container.querySelector('[data-place-result-id="place-1"]')
    if (!resultButton) {
      throw new Error('Expected a selectable place search result.')
    }

    act(() => {
      resultButton.click()
    })

    await waitFor(() => {
      const latitudeInput = container.querySelector('#cx-latitude')
      const longitudeInput = container.querySelector('#cx-longitude')
      const nextAddressInput = container.querySelector('#cx-address')

      if (!latitudeInput || !longitudeInput || !nextAddressInput) return false
      const { lat, lng } = expectedBd09(39.9928, 116.3055)
      if (latitudeInput.value !== lat) return false
      if (longitudeInput.value !== lng) return false
      if (!nextAddressInput.value.includes('北京大学')) return false

      return true
    })
  })

  test('manual coordinates win over a pending geolocation on the page', async () => {
    const requests = []
    vi.stubGlobal('navigator', {
      geolocation: {
        getCurrentPosition: vi.fn((onSuccess, onError, options) => {
          requests.push({ onSuccess, onError, options })
        }),
      },
    })

    await renderSignin(container, root)
    chooseLocationSignType(container)

    const useLocationButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('使用当前位置')
    )
    act(() => useLocationButton.click())
    expect(requests).toHaveLength(1)

    setInputValue(container.querySelector('#cx-latitude'), 'manual-latitude')
    setInputValue(container.querySelector('#cx-longitude'), 'manual-longitude')
    act(() => requests[0].onSuccess({ coords: { latitude: 31.2304, longitude: 121.4737 } }))

    await waitFor(() => (
      container.querySelector('#cx-latitude')?.value === 'manual-latitude' &&
      container.querySelector('#cx-longitude')?.value === 'manual-longitude'
    ))
  })

  test('map confirmation wins over a pending geolocation on the page', async () => {
    const requests = []
    vi.stubGlobal('navigator', {
      geolocation: {
        getCurrentPosition: vi.fn((onSuccess, onError, options) => {
          requests.push({ onSuccess, onError, options })
        }),
      },
    })

    await renderSignin(container, root)
    chooseLocationSignType(container)

    const useLocationButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('使用当前位置')
    )
    act(() => useLocationButton.click())
    expect(requests).toHaveLength(1)

    const mapButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('在地图上选点')
    )
    act(() => mapButton.click())
    await waitFor(() => container.querySelector('[data-testid="mock-map-confirm"]'))

    act(() => container.querySelector('[data-testid="mock-map-confirm"]').click())
    const { lat, lng } = expectedBd09(31.2304, 121.4737)
    act(() => requests[0].onSuccess({ coords: { latitude: 39.9042, longitude: 116.4074 } }))

    await waitFor(() => (
      container.querySelector('#cx-latitude')?.value === lat &&
      container.querySelector('#cx-longitude')?.value === lng
    ))
  })

  test('manual coordinates win over a pending geocode on the page', async () => {
    const pending = deferred()
    globalThis.fetch.mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/api/v1/chaoxing/location/geocode')) return pending.promise
      if (url.includes('/api/v1/chaoxing/location/search')) return mockPlaceSearchResponse
      return mockBootstrapResponse({ data: [] })
    })

    await renderSignin(container, root)
    chooseLocationSignType(container)
    setInputValue(container.querySelector('#cx-address'), '旧地址')

    const resolveButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('解析坐标')
    )
    act(() => resolveButton.click())
    await waitFor(() => resolveButton.textContent?.includes('解析中...'))

    setInputValue(container.querySelector('#cx-latitude'), 'manual-latitude')
    setInputValue(container.querySelector('#cx-longitude'), 'manual-longitude')
    await act(async () => {
      pending.resolve(mockGeocodeResponse)
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(container.querySelector('#cx-latitude').value).toBe('manual-latitude')
    expect(container.querySelector('#cx-longitude').value).toBe('manual-longitude')
  })

})
