import { useCallback, useEffect, useRef, useState } from 'react'

import { normalizeBaiduLocationResult, normalizeBaiduPlaceCandidates } from '../../../services/baiduLocation'
import { wgs84ToBd09 } from '../../../utils/coordTransform'

export default function useLocationServices(requestChaoxingApi, setForm) {
  const latestAddressRef = useRef('')
  const geocodeRequestIdRef = useRef(0)
  const placeSearchRequestIdRef = useRef(0)
  const geolocationGenerationRef = useRef(0)
  const geocodeLoadingOwnerRef = useRef(null)
  const placeSearchLoadingOwnerRef = useRef(null)
  const mountedRef = useRef(false)

  const [geocodeLoading, setGeocodeLoading] = useState(false)
  const [geocodeMessage, setGeocodeMessage] = useState('')
  const [geocodeStatus, setGeocodeStatus] = useState('info')
  const [placeSearchLoading, setPlaceSearchLoading] = useState(false)
  const [placeSearchResults, setPlaceSearchResults] = useState([])
  const [placeSearchMessage, setPlaceSearchMessage] = useState('')
  const [isMapPickerOpen, setIsMapPickerOpen] = useState(false)

  useEffect(() => {
    mountedRef.current = true

    return () => {
      mountedRef.current = false
      geocodeRequestIdRef.current += 1
      placeSearchRequestIdRef.current += 1
      geolocationGenerationRef.current += 1
      geocodeLoadingOwnerRef.current = null
      placeSearchLoadingOwnerRef.current = null
    }
  }, [])

  // Every user-owned coordinate intent invalidates all older async sources.
  // The loading owners let stale finally blocks leave a newer request alone.
  const beginLocationIntent = useCallback(() => {
    const generations = {
      geolocation: geolocationGenerationRef.current + 1,
      geocode: geocodeRequestIdRef.current + 1,
      placeSearch: placeSearchRequestIdRef.current + 1,
    }
    geolocationGenerationRef.current = generations.geolocation
    geocodeRequestIdRef.current = generations.geocode
    placeSearchRequestIdRef.current = generations.placeSearch

    if (geocodeLoadingOwnerRef.current !== null) {
      geocodeLoadingOwnerRef.current = null
      setGeocodeLoading(false)
    }
    if (placeSearchLoadingOwnerRef.current !== null) {
      placeSearchLoadingOwnerRef.current = null
      setPlaceSearchLoading(false)
    }

    return generations
  }, [])

  const handleAddressChange = useCallback((value) => {
    const nextAddress = String(value ?? '')

    beginLocationIntent()
    latestAddressRef.current = nextAddress
    // Invalidate every coordinate request on every edit, even when the user changes
    // back to the original text before an older request resolves.
    setGeocodeStatus('info')
    setGeocodeMessage(nextAddress.trim() ? '地址已变更，请重新解析坐标。' : '')
    setPlaceSearchResults([])
    setPlaceSearchMessage('')
    setForm((prev) => ({
      ...prev,
      address: nextAddress,
      latitude: '',
      longitude: '',
      altitude: '',
    }))
  }, [beginLocationIntent, setForm])

  // Inputs arrive as WGS-84 (from the Photon-backed API and the OSM map picker).
  // Chaoxing expects Baidu BD-09 coordinates, so convert once at this boundary.
  const applyResolvedLocation = useCallback((location, { convert = true } = {}) => {
    // Honour an explicitly-provided address even when it's empty — geolocation
    // passes address:'' to clear a previously-typed place so stale coordinates
    // and a mismatched address can't be submitted together.
    const hasAddress = location.address !== undefined
    if (hasAddress) latestAddressRef.current = location.address
    const hasLatitude = location.latitude !== undefined
    const hasLongitude = location.longitude !== undefined
    const wgsLat = Number(location.latitude)
    const wgsLng = Number(location.longitude)
    let latOut = location.latitude
    let lngOut = location.longitude
    if (convert && hasLatitude && hasLongitude && Number.isFinite(wgsLat) && Number.isFinite(wgsLng)) {
      const [bdLng, bdLat] = wgs84ToBd09(wgsLng, wgsLat)
      latOut = String(bdLat)
      lngOut = String(bdLng)
    }
    setForm((prev) => ({
      ...prev,
      address: hasAddress ? location.address : prev.address,
      ...(hasLatitude ? { latitude: latOut } : {}),
      ...(hasLongitude ? { longitude: lngOut } : {}),
    }))
  }, [setForm])

  const applyUserLocationIntent = useCallback((location, options) => {
    beginLocationIntent()
    applyResolvedLocation(location, options)
  }, [applyResolvedLocation, beginLocationIntent])

  // Browser geolocation returns WGS-84, which applyResolvedLocation converts to
  // BD-09 for us — so this is the lowest-friction way to fill in coordinates.
  const useCurrentLocation = useCallback(() => {
    const { geolocation: generation } = beginLocationIntent()
    const owner = { kind: 'geolocation', generation }
    const isCurrentGeneration = () => mountedRef.current && geolocationGenerationRef.current === owner.generation

    if (!isCurrentGeneration()) return

    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setGeocodeStatus('error')
      setGeocodeMessage('当前环境不支持定位，请改用地图选点或地址解析。')
      return
    }
    geocodeLoadingOwnerRef.current = owner
    const isCurrentOwner = () => isCurrentGeneration() && geocodeLoadingOwnerRef.current === owner
    setGeocodeLoading(true)
    setGeocodeStatus('info')
    setGeocodeMessage('正在获取当前位置…')

    const finish = () => {
      if (isCurrentOwner()) {
        geocodeLoadingOwnerRef.current = null
        setGeocodeLoading(false)
      }
    }

    const handleGeolocationError = (error) => {
      if (!isCurrentOwner()) return

      try {
        setGeocodeStatus('error')
        setGeocodeMessage(
          error?.code === 1 ? '定位权限被拒绝，请在浏览器允许定位后重试。' : '获取当前位置失败，请稍后重试。'
        )
      } finally {
        finish()
      }
    }

    try {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          if (!isCurrentOwner()) return

          try {
            // Clear any previously-typed address so it can't be paired with the
            // new GPS coordinates (location signin only needs lat/lng).
            applyResolvedLocation({
              latitude: position.coords.latitude,
              longitude: position.coords.longitude,
              address: '',
            })
            if (!isCurrentOwner()) return
            setGeocodeStatus('success')
            setGeocodeMessage('已使用当前位置填入坐标。')
          } finally {
            finish()
          }
        },
        handleGeolocationError,
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
      )
    } catch (error) {
      if (!isCurrentOwner()) return
      handleGeolocationError(error)
    }
  }, [applyResolvedLocation, beginLocationIntent])

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

    const { geocode: requestId } = beginLocationIntent()
    const owner = { kind: 'geocode', generation: requestId }
    geocodeLoadingOwnerRef.current = owner
    setGeocodeLoading(true)
    latestAddressRef.current = address
    setGeocodeStatus('info')
    setGeocodeMessage('正在解析坐标...')
    const isCurrentOwner = () => (
      mountedRef.current &&
      geocodeRequestIdRef.current === requestId &&
      geocodeLoadingOwnerRef.current === owner
    )

    try {
      const resp = await requestChaoxingApi(`/location/geocode?query=${encodeURIComponent(address)}`, null, { method: 'GET' })
      if (!isCurrentOwner()) {
        return
      }
      if (latestAddressRef.current.trim() !== address) {
        setGeocodeStatus('info')
        setGeocodeMessage('地址已变更，请重新解析坐标。')
        return
      }
      const resolved = normalizeBaiduLocationResult(resp)
      applyResolvedLocation(resolved)
      if (isCurrentOwner()) {
        setGeocodeStatus('success')
        setGeocodeMessage(`已解析：${resolved.latitude}, ${resolved.longitude}`)
      }
    } catch (err) {
      if (!isCurrentOwner()) {
        return
      }
      setGeocodeStatus('error')
      setGeocodeMessage(err.message || '地点解析失败，请稍后重试')
    } finally {
      if (isCurrentOwner()) {
        geocodeLoadingOwnerRef.current = null
        setGeocodeLoading(false)
      }
    }
  }, [applyResolvedLocation, beginLocationIntent, requestChaoxingApi])

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

    const { placeSearch: requestId } = beginLocationIntent()
    const owner = { kind: 'place-search', generation: requestId }
    placeSearchLoadingOwnerRef.current = owner
    setPlaceSearchLoading(true)
    latestAddressRef.current = query
    setPlaceSearchResults([])
    setPlaceSearchMessage('正在搜索地点...')
    const isCurrentOwner = () => (
      mountedRef.current &&
      placeSearchRequestIdRef.current === requestId &&
      placeSearchLoadingOwnerRef.current === owner
    )

    try {
      const resp = await requestChaoxingApi(`/location/search?query=${encodeURIComponent(query)}`, null, { method: 'GET' })
      if (!isCurrentOwner()) {
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
      if (!isCurrentOwner()) {
        return
      }
      setPlaceSearchResults([])
      setPlaceSearchMessage(err.message || '地点搜索失败，请稍后重试')
    } finally {
      if (isCurrentOwner()) {
        placeSearchLoadingOwnerRef.current = null
        setPlaceSearchLoading(false)
      }
    }
  }, [beginLocationIntent, requestChaoxingApi])

  const choosePlaceSearchResult = useCallback((candidate) => {
    applyUserLocationIntent({
      ...candidate,
      address: [candidate.name, candidate.address].filter(Boolean).join(' '),
    })
    setPlaceSearchResults([])
    setPlaceSearchMessage(`已选择地点：${candidate.name || candidate.address}`)
    setGeocodeStatus('success')
    setGeocodeMessage(`已选坐标：${candidate.latitude}, ${candidate.longitude}`)
  }, [applyUserLocationIntent])

  return {
    latestAddressRef,
    geocodeLoading,
    geocodeMessage,
    geocodeStatus,
    setGeocodeStatus,
    setGeocodeMessage,
    handleAddressChange,
    placeSearchLoading,
    placeSearchResults,
    placeSearchMessage,
    isMapPickerOpen,
    setIsMapPickerOpen,
    applyUserLocationIntent,
    useCurrentLocation,
    resolveLocationCoordinates,
    searchLocationCandidates,
    choosePlaceSearchResult,
  }
}
