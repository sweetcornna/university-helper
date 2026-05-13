import { useCallback, useEffect, useRef, useState } from 'react'
import { MapPin, Search, X, Loader2 } from 'lucide-react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import markerIcon from 'leaflet/dist/images/marker-icon.png'
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png'
import markerShadow from 'leaflet/dist/images/marker-shadow.png'
import { getToken } from '../utils/auth'
import { bd09ToWgs84, wgs84ToBd09 } from '../utils/coordTransform'

const DEFAULT_CENTER = [39.9042, 116.4074]
const DEFAULT_ZOOM = 15
const REVERSE_GEOCODE_URL = '/api/v1/chaoxing/location/reverse-geocode'
const PLACE_SEARCH_URL = '/api/v1/chaoxing/location/search'

// Resolve Leaflet default marker icons via the Vite asset pipeline so we
// don't rely on a third-party CDN (unpkg) at runtime.
delete L.Icon.Default.prototype._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
})

const fetchJson = async (url) => {
  const token = getToken()
  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) throw new Error('请求失败')
  return res.json()
}

export default function BaiduMapPickerModal({ open, initialLocation, onClose, onConfirm }) {
  const mapContainerRef = useRef(null)
  const mapRef = useRef(null)
  const markerRef = useRef(null)

  const [draft, setDraft] = useState(null)
  const [reverseLoading, setReverseLoading] = useState(false)

  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState('')

  // Initialize map when modal opens
  useEffect(() => {
    if (!open || !mapContainerRef.current || mapRef.current) return

    let centerLat = DEFAULT_CENTER[0]
    let centerLng = DEFAULT_CENTER[1]
    let hasInitial = false
    if (initialLocation?.latitude && initialLocation?.longitude) {
      // Form stores BD-09; convert to WGS-84 for the OSM map.
      const bdLat = Number(initialLocation.latitude)
      const bdLng = Number(initialLocation.longitude)
      if (Number.isFinite(bdLat) && Number.isFinite(bdLng)) {
        const [wgsLng, wgsLat] = bd09ToWgs84(bdLng, bdLat)
        centerLat = wgsLat
        centerLng = wgsLng
        hasInitial = true
      }
    }

    const map = L.map(mapContainerRef.current).setView([centerLat, centerLng], DEFAULT_ZOOM)

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 19,
    }).addTo(map)

    mapRef.current = map

    // Place initial marker if coordinates exist
    if (hasInitial) {
      const marker = L.marker([centerLat, centerLng]).addTo(map)
      markerRef.current = marker
      setDraft({
        address: initialLocation.address || '',
        latitude: String(centerLat),
        longitude: String(centerLng),
        source: '表单已有坐标',
      })
    }

    // Map click handler
    map.on('click', (e) => {
      const { lat, lng } = e.latlng
      placeMarker(lat, lng, '地图点击')
      reverseGeocode(lat, lng)
    })

    // Leaflet needs a resize nudge after the container becomes visible
    setTimeout(() => map.invalidateSize(), 100)

    return () => {
      // will be cleaned up by the close effect
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  // Cleanup map on modal close
  useEffect(() => {
    if (!open) {
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
      markerRef.current = null
      setDraft(null)
      setSearchQuery('')
      setSearchResults([])
      setSearchError('')
    }
  }, [open])

  const placeMarker = useCallback((lat, lng, source) => {
    const map = mapRef.current
    if (!map) return

    if (markerRef.current) {
      markerRef.current.setLatLng([lat, lng])
    } else {
      const marker = L.marker([lat, lng]).addTo(map)
      markerRef.current = marker
    }

    map.panTo([lat, lng])
    setDraft({
      address: '',
      latitude: String(lat),
      longitude: String(lng),
      source: source || '',
    })
  }, [])

  const reverseGeocode = useCallback(async (lat, lng) => {
    setReverseLoading(true)
    try {
      const data = await fetchJson(
        `${REVERSE_GEOCODE_URL}?lat=${lat}&lng=${lng}`
      )
      const address = data?.data?.address || '未解析到详细地址'
      setDraft((prev) =>
        prev && prev.latitude === String(lat) && prev.longitude === String(lng)
          ? { ...prev, address }
          : prev
      )
    } catch {
      setDraft((prev) =>
        prev && prev.latitude === String(lat) && prev.longitude === String(lng)
          ? { ...prev, address: '未解析到详细地址' }
          : prev
      )
    } finally {
      setReverseLoading(false)
    }
  }, [])

  const handleSearch = useCallback(async () => {
    const q = searchQuery.trim()
    if (!q) return
    setSearchLoading(true)
    setSearchError('')
    setSearchResults([])
    try {
      const data = await fetchJson(
        `${PLACE_SEARCH_URL}?query=${encodeURIComponent(q)}`
      )
      const results = data?.data?.results || []
      if (results.length === 0) {
        setSearchError('未找到相关地点')
      } else {
        setSearchResults(results)
      }
    } catch {
      setSearchError('搜索失败，请稍后重试')
    } finally {
      setSearchLoading(false)
    }
  }, [searchQuery])

  const handleSearchKeyDown = useCallback(
    (e) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        handleSearch()
      }
    },
    [handleSearch]
  )

  const selectCandidate = useCallback(
    (candidate) => {
      const lat = Number(candidate.latitude)
      const lng = Number(candidate.longitude)
      placeMarker(lat, lng, '搜索结果')
      const address = [candidate.name, candidate.address].filter(Boolean).join(' ')
      setDraft({
        address,
        latitude: String(lat),
        longitude: String(lng),
        source: '搜索结果',
      })
      setSearchResults([])
      setSearchQuery('')
    },
    [placeMarker]
  )

  const handleConfirm = useCallback(() => {
    if (!draft) return
    onConfirm({
      address: draft.address,
      latitude: draft.latitude,
      longitude: draft.longitude,
    })
  }, [draft, onConfirm])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="relative flex h-[85vh] w-[90vw] max-w-4xl flex-col overflow-hidden rounded-2xl border border-white/20 bg-white/95 shadow-2xl backdrop-blur-lg">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div className="flex items-center gap-2">
            <MapPin className="h-5 w-5 text-blue-600" />
            <h2 className="text-lg font-semibold text-gray-800">地图选点</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex min-h-0 flex-1 flex-col md:flex-row">
          {/* Left panel: search + results + preview */}
          <div className="flex w-full flex-col border-b border-gray-200 md:w-80 md:border-b-0 md:border-r">
            {/* Search */}
            <div className="border-b border-gray-100 p-4">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={handleSearchKeyDown}
                  placeholder="搜索地点名称..."
                  className="min-w-0 flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm outline-none transition-colors focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                />
                <button
                  type="button"
                  onClick={handleSearch}
                  disabled={searchLoading || !searchQuery.trim()}
                  className="flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
                >
                  {searchLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Search className="h-4 w-4" />
                  )}
                </button>
              </div>
              {searchError && (
                <p className="mt-2 text-xs text-red-500">{searchError}</p>
              )}
            </div>

            {/* Search results */}
            {searchResults.length > 0 && (
              <div className="flex-1 overflow-y-auto p-2">
                {searchResults.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => selectCandidate(c)}
                    className="mb-1 w-full rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-blue-50"
                  >
                    <span className="block text-sm font-medium text-gray-800">
                      {c.name || c.address}
                    </span>
                    {c.address && (
                      <span className="mt-0.5 block text-xs text-gray-500">
                        {c.address}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}

            {/* Preview */}
            {draft && (
              <div className="mt-auto border-t border-gray-100 p-4">
                <p className="mb-1 text-xs font-medium text-gray-400">
                  当前选点 {draft.source ? `(${draft.source})` : ''}
                </p>
                <p className="text-sm text-gray-700">
                  {reverseLoading ? (
                    <span className="flex items-center gap-1 text-gray-400">
                      <Loader2 className="h-3 w-3 animate-spin" /> 解析地址中...
                    </span>
                  ) : (
                    draft.address || '未解析到详细地址'
                  )}
                </p>
                <p className="mt-1 font-mono text-xs text-gray-500">
                  {(() => {
                    const [bdLng, bdLat] = wgs84ToBd09(
                      Number(draft.longitude),
                      Number(draft.latitude)
                    )
                    return `${bdLat.toFixed(6)}, ${bdLng.toFixed(6)} (BD-09)`
                  })()}
                </p>
              </div>
            )}
          </div>

          {/* Map area */}
          <div className="relative min-h-[300px] flex-1">
            <div ref={mapContainerRef} className="h-full w-full" />
            {!draft && (
              <div className="pointer-events-none absolute bottom-4 left-1/2 z-[1000] -translate-x-1/2 rounded-lg bg-black/60 px-4 py-2 text-sm text-white">
                点击地图或搜索地点来选取位置
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-gray-200 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={!draft}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
          >
            确认选点
          </button>
        </div>
      </div>
    </div>
  )
}
