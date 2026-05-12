import { act } from 'react-dom/test-utils'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import ChaoxingSignin from './ChaoxingSignin'
import { wgs84ToBd09 } from '../utils/coordTransform'

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
})
