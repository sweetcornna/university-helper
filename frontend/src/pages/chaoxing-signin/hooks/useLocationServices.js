import { useCallback, useRef, useState } from 'react'

import { normalizeBaiduLocationResult, normalizeBaiduPlaceCandidates } from '../../../services/baiduLocation'
import { wgs84ToBd09 } from '../../../utils/coordTransform'

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

  // Inputs arrive as WGS-84 (from the Photon-backed API and the OSM map picker).
  // Chaoxing expects Baidu BD-09 coordinates, so convert once at this boundary.
  const applyResolvedLocation = useCallback((location) => {
    // Honour an explicitly-provided address even when it's empty — geolocation
    // passes address:'' to clear a previously-typed place so stale coordinates
    // and a mismatched address can't be submitted together.
    const hasAddress = location.address !== undefined
    if (hasAddress) latestAddressRef.current = location.address
    const wgsLat = Number(location.latitude)
    const wgsLng = Number(location.longitude)
    let latOut = location.latitude
    let lngOut = location.longitude
    if (Number.isFinite(wgsLat) && Number.isFinite(wgsLng)) {
      const [bdLng, bdLat] = wgs84ToBd09(wgsLng, wgsLat)
      latOut = String(bdLat)
      lngOut = String(bdLng)
    }
    setForm((prev) => ({
      ...prev,
      address: hasAddress ? location.address : prev.address,
      latitude: latOut,
      longitude: lngOut,
    }))
  }, [setForm])

  // Browser geolocation returns WGS-84, which applyResolvedLocation converts to
  // BD-09 for us — so this is the lowest-friction way to fill in coordinates.
  const useCurrentLocation = useCallback(() => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setGeocodeStatus('error')
      setGeocodeMessage('当前环境不支持定位，请改用地图选点或地址解析。')
      return
    }
    setGeocodeStatus('info')
    setGeocodeMessage('正在获取当前位置…')
    navigator.geolocation.getCurrentPosition(
      (position) => {
        // Clear any previously-typed address so it can't be paired with the
        // new GPS coordinates (location signin only needs lat/lng).
        applyResolvedLocation({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          address: '',
        })
        setGeocodeStatus('success')
        setGeocodeMessage('已使用当前位置填入坐标。')
      },
      (error) => {
        setGeocodeStatus('error')
        setGeocodeMessage(
          error?.code === 1 ? '定位权限被拒绝，请在浏览器允许定位后重试。' : '获取当前位置失败，请稍后重试。'
        )
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    )
  }, [applyResolvedLocation])

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
    useCurrentLocation,
    resolveLocationCoordinates,
    searchLocationCandidates,
    choosePlaceSearchResult,
  }
}
