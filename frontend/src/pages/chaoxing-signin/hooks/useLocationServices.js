import { useCallback, useRef, useState } from 'react'

import { normalizeBaiduLocationResult, normalizeBaiduPlaceCandidates } from '../../../services/baiduLocation'

export default function useLocationServices(requestChaoxingApi, setForm) {
  const latestAddressRef = useRef('')
  const geocodeRequestIdRef = useRef(0)
  const placeSearchRequestIdRef = useRef(0)

  const [geocodeLoading, setGeocodeLoading] = useState(false)
  const [geocodeMessage, setGeocodeMessage] = useState('')
  const [geocodeStatus, setGeocodeStatus] = useState('info')
  const [placeSearchLoading, setPlaceSearchLoading] = useState(false)
  const [placeSearchResults, setPlaceSearchResults] = useState([])
  const [placeSearchMessage, setPlaceSearchMessage] = useState('')
  const [isMapPickerOpen, setIsMapPickerOpen] = useState(false)

  const applyResolvedLocation = useCallback((location) => {
    latestAddressRef.current = location.address || latestAddressRef.current
    setForm((prev) => ({
      ...prev,
      address: location.address || prev.address,
      latitude: location.latitude,
      longitude: location.longitude,
    }))
  }, [setForm])

  const resolveLocationCoordinates = useCallback(async () => {
    const liveAddressInput = document.getElementById('cx-address')
    const liveAddress =
      liveAddressInput instanceof HTMLInputElement ? liveAddressInput.value : latestAddressRef.current
    const address = String(liveAddress || latestAddressRef.current).trim()
    if (!address) {
      setGeocodeStatus('error')
      setGeocodeMessage('请先输入地址后再解析坐标。')
      return
    }

    setGeocodeLoading(true)
    latestAddressRef.current = address
    setGeocodeStatus('info')
    setGeocodeMessage('正在解析坐标...')
    const requestId = geocodeRequestIdRef.current + 1
    geocodeRequestIdRef.current = requestId

    try {
      const resp = await requestChaoxingApi(`/location/geocode?query=${encodeURIComponent(address)}`, null, { method: 'GET' })
      if (geocodeRequestIdRef.current !== requestId) {
        return
      }
      if (latestAddressRef.current.trim() !== address) {
        setGeocodeStatus('info')
        setGeocodeMessage('地址已变更，请重新解析坐标。')
        return
      }
      const resolved = normalizeBaiduLocationResult(resp)
      applyResolvedLocation(resolved)
      setGeocodeStatus('success')
      setGeocodeMessage(`已解析：${resolved.latitude}, ${resolved.longitude}`)
    } catch (err) {
      if (geocodeRequestIdRef.current !== requestId) {
        return
      }
      setGeocodeStatus('error')
      setGeocodeMessage(err.message || '地点解析失败，请稍后重试')
    } finally {
      setGeocodeLoading(false)
    }
  }, [applyResolvedLocation, requestChaoxingApi])

  const searchLocationCandidates = useCallback(async () => {
    const liveAddressInput = document.getElementById('cx-address')
    const liveAddress =
      liveAddressInput instanceof HTMLInputElement ? liveAddressInput.value : latestAddressRef.current
    const query = String(liveAddress || latestAddressRef.current).trim()
    if (!query) {
      setPlaceSearchResults([])
      setPlaceSearchMessage('请先输入地名后再搜索地点。')
      return
    }

    setPlaceSearchLoading(true)
    latestAddressRef.current = query
    setPlaceSearchResults([])
    setPlaceSearchMessage('正在搜索地点...')
    const requestId = placeSearchRequestIdRef.current + 1
    placeSearchRequestIdRef.current = requestId

    try {
      const resp = await requestChaoxingApi(`/location/search?query=${encodeURIComponent(query)}`, null, { method: 'GET' })
      if (placeSearchRequestIdRef.current !== requestId) {
        return
      }
      if (latestAddressRef.current.trim() !== query) {
        setPlaceSearchMessage('地名已变更，请重新搜索。')
        return
      }
      const results = normalizeBaiduPlaceCandidates(resp)
      setPlaceSearchResults(results)
      setPlaceSearchMessage(results.length > 0 ? `找到 ${results.length} 个地点，请选择最接近的一个。` : '未找到可选地点')
    } catch (err) {
      if (placeSearchRequestIdRef.current !== requestId) {
        return
      }
      setPlaceSearchResults([])
      setPlaceSearchMessage(err.message || '地点搜索失败，请稍后重试')
    } finally {
      setPlaceSearchLoading(false)
    }
  }, [requestChaoxingApi])

  const choosePlaceSearchResult = useCallback((candidate) => {
    applyResolvedLocation({
      ...candidate,
      address: [candidate.name, candidate.address].filter(Boolean).join(' '),
    })
    setPlaceSearchResults([])
    setPlaceSearchMessage(`已选择地点：${candidate.name || candidate.address}`)
    setGeocodeStatus('success')
    setGeocodeMessage(`已选坐标：${candidate.latitude}, ${candidate.longitude}`)
  }, [applyResolvedLocation])

  return {
    latestAddressRef,
    geocodeLoading,
    geocodeMessage,
    geocodeStatus,
    setGeocodeStatus,
    setGeocodeMessage,
    placeSearchLoading,
    placeSearchResults,
    placeSearchMessage,
    isMapPickerOpen,
    setIsMapPickerOpen,
    applyResolvedLocation,
    resolveLocationCoordinates,
    searchLocationCandidates,
    choosePlaceSearchResult,
  }
}
