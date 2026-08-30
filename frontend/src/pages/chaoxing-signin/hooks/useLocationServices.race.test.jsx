import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { fireEvent } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'

import useLocationServices from './useLocationServices'
import { wgs84ToBd09 } from '../../../utils/coordTransform'

const deferred = () => {
  let resolve
  let reject
  const promise = new Promise((promiseResolve, promiseReject) => {
    resolve = promiseResolve
    reject = promiseReject
  })
  return { promise, resolve, reject }
}

const geocodeResponse = (address) => ({
  result: {
    formatted_address: address,
    location: { lat: 39.9042, lng: 116.4074 },
  },
})

const placeSearchResponse = (name) => ({
  results: [{
    uid: name,
    name,
    address: `${name} 地址`,
    location: { lat: 39.9042, lng: 116.4074 },
  }],
})

const deferredGeolocation = () => {
  const requests = []
  const geolocation = {
    getCurrentPosition: vi.fn((onSuccess, onError, options) => {
      requests.push({ onSuccess, onError, options })
    }),
  }
  return { geolocation, requests }
}

const position = (latitude, longitude) => ({ coords: { latitude, longitude } })

const expectedCoordinates = (latitude, longitude) => {
  const [bdLongitude, bdLatitude] = wgs84ToBd09(longitude, latitude)
  return { latitude: String(bdLatitude), longitude: String(bdLongitude) }
}

function LocationServicesHarness({ requestChaoxingApi, setForm, onReady }) {
  const services = useLocationServices(requestChaoxingApi, setForm)
  onReady(services)

  return (
    <>
      <input id="cx-address" defaultValue="" />
      <output data-testid="geocode-loading">{String(services.geocodeLoading)}</output>
      <output data-testid="geocode-status">{services.geocodeStatus}</output>
      <output data-testid="geocode-message">{services.geocodeMessage}</output>
      <output data-testid="place-search-loading">{String(services.placeSearchLoading)}</output>
      <output data-testid="place-search-message">{services.placeSearchMessage}</output>
      <output data-testid="place-search-results">{JSON.stringify(services.placeSearchResults)}</output>
    </>
  )
}

const renderLocationServices = (requestChaoxingApi, setForm = vi.fn()) => {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  let current

  act(() => {
    root.render(
      <LocationServicesHarness
        requestChaoxingApi={requestChaoxingApi}
        setForm={setForm}
        onReady={(services) => {
          current = services
        }}
      />
    )
  })

  return {
    container,
    setForm,
    get current() {
      return current
    },
    cleanup: () => {
      act(() => root.unmount())
      container.remove()
    },
  }
}

const setAddress = async (rendered, value) => {
  await act(async () => {
    fireEvent.change(rendered.container.querySelector('#cx-address'), { target: { value } })
  })
}

const editAddress = async (rendered, value) => {
  await act(async () => {
    const input = rendered.container.querySelector('#cx-address')
    input.value = value
    rendered.current.handleAddressChange(value)
  })
}

const startRequest = async (rendered, method, address) => {
  await setAddress(rendered, address)
  let requestPromise
  await act(async () => {
    requestPromise = rendered.current[method]()
    await Promise.resolve()
  })
  return { promise: requestPromise }
}

const settleRequest = async (requestPromise, settle) => {
  await act(async () => {
    settle()
    await requestPromise
  })
}

const cases = [
  {
    label: 'geocode',
    method: 'resolveLocationCoordinates',
    loadingTestId: 'geocode-loading',
    messageTestId: 'geocode-message',
    response: geocodeResponse,
    successMessage: '已解析：',
  },
  {
    label: 'place search',
    method: 'searchLocationCandidates',
    loadingTestId: 'place-search-loading',
    messageTestId: 'place-search-message',
    response: placeSearchResponse,
    successMessage: '找到 1 个地点',
  },
]

describe('useLocationServices overlapping request loading', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  test.each(cases)('$label keeps loading while the newer request is pending after a stale resolve', async ({
    label,
    method,
    loadingTestId,
    messageTestId,
    response,
    successMessage,
  }) => {
    const first = deferred()
    const second = deferred()
    let requestCount = 0
    const requestChaoxingApi = vi.fn(() => {
      requestCount += 1
      return (requestCount === 1 ? first : second).promise
    })
    const rendered = renderLocationServices(requestChaoxingApi)

    try {
      const firstPromise = await startRequest(rendered, method, '地址 A')
      const secondPromise = await startRequest(rendered, method, '地址 B')

      await settleRequest(firstPromise.promise, () => first.resolve(response('地址 A')))

      expect(rendered.container.querySelector(`[data-testid="${loadingTestId}"]`)).toHaveTextContent('true')
      expect(rendered.container.querySelector(`[data-testid="${messageTestId}"]`)).toHaveTextContent('正在')
      if (label === 'place search') {
        expect(rendered.container.querySelector('[data-testid="place-search-results"]')).toHaveTextContent('[]')
      } else {
        expect(rendered.setForm).not.toHaveBeenCalled()
      }

      await settleRequest(secondPromise.promise, () => second.resolve(response('地址 B')))

      expect(rendered.container.querySelector(`[data-testid="${loadingTestId}"]`)).toHaveTextContent('false')
      expect(rendered.container.querySelector(`[data-testid="${messageTestId}"]`)).toHaveTextContent(successMessage)
    } finally {
      rendered.cleanup()
    }
  })

  test.each(cases)('$label keeps loading while the newer request is pending after a stale rejection', async ({
    method,
    loadingTestId,
    messageTestId,
    response,
    successMessage,
  }) => {
    const first = deferred()
    const second = deferred()
    let requestCount = 0
    const requestChaoxingApi = vi.fn(() => {
      requestCount += 1
      return (requestCount === 1 ? first : second).promise
    })
    const rendered = renderLocationServices(requestChaoxingApi)

    try {
      const firstPromise = await startRequest(rendered, method, '地址 A')
      const secondPromise = await startRequest(rendered, method, '地址 B')

      await settleRequest(firstPromise.promise, () => first.reject(new Error('地址 A 失败')))

      expect(rendered.container.querySelector(`[data-testid="${loadingTestId}"]`)).toHaveTextContent('true')
      expect(rendered.container.querySelector(`[data-testid="${messageTestId}"]`)).toHaveTextContent('正在')

      await settleRequest(secondPromise.promise, () => second.resolve(response('地址 B')))

      expect(rendered.container.querySelector(`[data-testid="${loadingTestId}"]`)).toHaveTextContent('false')
      expect(rendered.container.querySelector(`[data-testid="${messageTestId}"]`)).toHaveTextContent(successMessage)
    } finally {
      rendered.cleanup()
    }
  })

  test.each(cases)('$label ignores a response after the address is edited', async ({
    label,
    method,
    response,
  }) => {
    const first = deferred()
    const requestChaoxingApi = vi.fn(() => first.promise)
    const rendered = renderLocationServices(requestChaoxingApi)

    try {
      const firstPromise = await startRequest(rendered, method, '地址 A')
      await editAddress(rendered, '地址 B')
      const setFormCallsAfterEdit = rendered.setForm.mock.calls.length

      await settleRequest(firstPromise.promise, () => first.resolve(response('地址 A')))

      expect(rendered.setForm).toHaveBeenCalledTimes(setFormCallsAfterEdit)
      expect(rendered.container.querySelector('[data-testid="place-search-results"]')).toHaveTextContent('[]')
      expect(rendered.container.querySelector(`[data-testid="${label === 'geocode' ? 'geocode-message' : 'place-search-message'}"]`)).not.toHaveTextContent('地址 A')
      expect(rendered.container.querySelector(`[data-testid="${label === 'geocode' ? 'geocode-loading' : 'place-search-loading'}"]`)).toHaveTextContent('false')
    } finally {
      rendered.cleanup()
    }
  })

  test('address edits clear derived fields and existing place candidates', async () => {
    const form = {
      address: '地址 A',
      latitude: '39.9',
      longitude: '116.4',
      altitude: '100',
    }
    const setForm = vi.fn((update) => Object.assign(form, update(form)))
    const requestChaoxingApi = vi.fn(() => Promise.resolve(placeSearchResponse('地址 A')))
    const rendered = renderLocationServices(requestChaoxingApi, setForm)

    try {
      const searchPromise = await startRequest(rendered, 'searchLocationCandidates', '地址 A')
      await settleRequest(searchPromise.promise, () => {})
      expect(rendered.container.querySelector('[data-testid="place-search-results"]')).not.toHaveTextContent('[]')

      await editAddress(rendered, '地址 B')

      expect(form).toMatchObject({
        address: '地址 B',
        latitude: '',
        longitude: '',
        altitude: '',
      })
      expect(rendered.container.querySelector('[data-testid="place-search-results"]')).toHaveTextContent('[]')
      expect(rendered.container.querySelector('[data-testid="place-search-message"]').textContent).toBe('')
      expect(rendered.container.querySelector('[data-testid="geocode-message"]')).toHaveTextContent(
        '地址已变更，请重新解析坐标。'
      )
    } finally {
      rendered.cleanup()
    }
  })

  test.each([
    ['success', (request) => request.onSuccess(position(31.2304, 121.4737))],
    ['error', (request) => request.onError({ code: 2 })],
  ])('ignores a stale geolocation %s after the address is edited', async (_kind, settle) => {
    const { geolocation, requests } = deferredGeolocation()
    vi.stubGlobal('navigator', { geolocation })

    const form = {
      address: '',
      latitude: 'old-latitude',
      longitude: 'old-longitude',
      altitude: 'old-altitude',
    }
    const setForm = vi.fn((update) => Object.assign(form, update(form)))
    const rendered = renderLocationServices(vi.fn(), setForm)

    try {
      await editAddress(rendered, '地址 A')
      act(() => rendered.current.useCurrentLocation())
      expect(requests).toHaveLength(1)
      expect(rendered.container.querySelector('[data-testid="geocode-loading"]')).toHaveTextContent('true')

      await editAddress(rendered, '地址 B')
      const setFormCallsAfterEdit = setForm.mock.calls.length
      expect(form).toMatchObject({
        address: '地址 B',
        latitude: '',
        longitude: '',
        altitude: '',
      })
      expect(rendered.container.querySelector('[data-testid="geocode-message"]')).toHaveTextContent(
        '地址已变更，请重新解析坐标。'
      )

      act(() => settle(requests[0]))

      expect(setForm).toHaveBeenCalledTimes(setFormCallsAfterEdit)
      expect(form).toMatchObject({
        address: '地址 B',
        latitude: '',
        longitude: '',
        altitude: '',
      })
      expect(rendered.container.querySelector('[data-testid="geocode-message"]')).toHaveTextContent(
        '地址已变更，请重新解析坐标。'
      )
      expect(rendered.container.querySelector('[data-testid="geocode-loading"]')).toHaveTextContent('false')
    } finally {
      rendered.cleanup()
    }
  })

  test('only the latest geolocation result applies when callbacks resolve A then B', async () => {
    const { geolocation, requests } = deferredGeolocation()
    vi.stubGlobal('navigator', { geolocation })

    const form = { address: '', latitude: 'old-latitude', longitude: 'old-longitude', altitude: '' }
    const setForm = vi.fn((update) => Object.assign(form, update(form)))
    const rendered = renderLocationServices(vi.fn(), setForm)

    try {
      act(() => {
        rendered.current.useCurrentLocation()
        rendered.current.useCurrentLocation()
      })
      expect(requests).toHaveLength(2)
      expect(rendered.container.querySelector('[data-testid="geocode-loading"]')).toHaveTextContent('true')

      act(() => requests[0].onSuccess(position(31.2304, 121.4737)))

      expect(setForm).not.toHaveBeenCalled()
      expect(rendered.container.querySelector('[data-testid="geocode-loading"]')).toHaveTextContent('true')
      expect(rendered.container.querySelector('[data-testid="geocode-message"]')).toHaveTextContent(
        '正在获取当前位置…'
      )

      act(() => requests[1].onSuccess(position(22.5431, 114.0579)))

      expect(form).toMatchObject({ address: '', ...expectedCoordinates(22.5431, 114.0579) })
      expect(setForm).toHaveBeenCalledTimes(1)
      expect(rendered.container.querySelector('[data-testid="geocode-loading"]')).toHaveTextContent('false')
      expect(rendered.container.querySelector('[data-testid="geocode-message"]')).toHaveTextContent(
        '已使用当前位置填入坐标。'
      )
    } finally {
      rendered.cleanup()
    }
  })

  test('keeps the latest geolocation loading while an older error arrives first', async () => {
    const { geolocation, requests } = deferredGeolocation()
    vi.stubGlobal('navigator', { geolocation })

    const form = { address: '', latitude: '', longitude: '', altitude: '' }
    const setForm = vi.fn((update) => Object.assign(form, update(form)))
    const rendered = renderLocationServices(vi.fn(), setForm)

    try {
      act(() => {
        rendered.current.useCurrentLocation()
        rendered.current.useCurrentLocation()
      })

      act(() => requests[0].onError({ code: 1 }))

      expect(setForm).not.toHaveBeenCalled()
      expect(rendered.container.querySelector('[data-testid="geocode-loading"]')).toHaveTextContent('true')
      expect(rendered.container.querySelector('[data-testid="geocode-message"]')).toHaveTextContent(
        '正在获取当前位置…'
      )

      act(() => requests[1].onError({ code: 1 }))

      expect(rendered.container.querySelector('[data-testid="geocode-loading"]')).toHaveTextContent('false')
      expect(rendered.container.querySelector('[data-testid="geocode-message"]')).toHaveTextContent(
        '定位权限被拒绝，请在浏览器允许定位后重试。'
      )
    } finally {
      rendered.cleanup()
    }
  })

  test('ignores geolocation callbacks after unmount', async () => {
    const { geolocation, requests } = deferredGeolocation()
    vi.stubGlobal('navigator', { geolocation })

    const form = { address: '地址 A', latitude: '', longitude: '', altitude: '' }
    const setForm = vi.fn((update) => Object.assign(form, update(form)))
    const rendered = renderLocationServices(vi.fn(), setForm)

    act(() => rendered.current.useCurrentLocation())
    expect(requests).toHaveLength(1)
    const setFormCallsBeforeUnmount = setForm.mock.calls.length
    const latestAddressBeforeUnmount = rendered.current.latestAddressRef.current

    rendered.cleanup()

    act(() => {
      requests[0].onSuccess(position(31.2304, 121.4737))
      requests[0].onError({ code: 2 })
    })

    expect(setForm).toHaveBeenCalledTimes(setFormCallsBeforeUnmount)
    expect(rendered.current.latestAddressRef.current).toBe(latestAddressBeforeUnmount)
  })

  test('clears loading and reports the existing error when geolocation throws synchronously', () => {
    const error = new Error('geolocation unavailable')
    const geolocation = {
      getCurrentPosition: vi.fn(() => {
        throw error
      }),
    }
    vi.stubGlobal('navigator', { geolocation })

    const rendered = renderLocationServices(vi.fn())

    try {
      act(() => rendered.current.useCurrentLocation())

      expect(geolocation.getCurrentPosition).toHaveBeenCalledTimes(1)
      expect(rendered.container.querySelector('[data-testid="geocode-loading"]')).toHaveTextContent('false')
      expect(rendered.container.querySelector('[data-testid="geocode-status"]')).toHaveTextContent('error')
      expect(rendered.container.querySelector('[data-testid="geocode-message"]')).toHaveTextContent(
        '获取当前位置失败，请稍后重试。'
      )
    } finally {
      rendered.cleanup()
    }
  })

  test('a stale synchronous geolocation throw cannot stop a newer request', () => {
    const requests = []
    let rendered
    let hasThrown = false
    const geolocation = {
      getCurrentPosition: vi.fn((onSuccess, onError, options) => {
        if (!hasThrown) {
          hasThrown = true
          // Start the newer owner before the first browser call throws. This
          // models a re-entrant retry and exercises the stale catch path.
          rendered.current.useCurrentLocation()
          throw new Error('old geolocation unavailable')
        }
        requests.push({ onSuccess, onError, options })
      }),
    }
    vi.stubGlobal('navigator', { geolocation })

    rendered = renderLocationServices(vi.fn())

    try {
      act(() => rendered.current.useCurrentLocation())

      expect(geolocation.getCurrentPosition).toHaveBeenCalledTimes(2)
      expect(requests).toHaveLength(1)
      expect(rendered.container.querySelector('[data-testid="geocode-loading"]')).toHaveTextContent('true')
      expect(rendered.container.querySelector('[data-testid="geocode-status"]')).toHaveTextContent('info')
      expect(rendered.container.querySelector('[data-testid="geocode-message"]')).toHaveTextContent(
        '正在获取当前位置…'
      )

      act(() => requests[0].onSuccess(position(22.5431, 114.0579)))

      expect(rendered.container.querySelector('[data-testid="geocode-loading"]')).toHaveTextContent('false')
      expect(rendered.container.querySelector('[data-testid="geocode-status"]')).toHaveTextContent('success')
    } finally {
      rendered.cleanup()
    }
  })
})
