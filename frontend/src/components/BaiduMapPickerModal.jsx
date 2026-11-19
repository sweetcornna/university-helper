import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Search, X, Loader2 } from 'lucide-react'
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
const MAP_REQUEST_TIMEOUT_MS = 20000

// Resolve Leaflet default marker icons via the Vite asset pipeline so we
// don't rely on a third-party CDN (unpkg) at runtime.
delete L.Icon.Default.prototype._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
})

const fetchJson = async (url, { signal: callerSignal } = {}) => {
  const token = getToken()
  const controller = new AbortController()
  let timeoutId
  let rejectCallerAbort
  let callerAbortHandler

  const request = (async () => {
    const res = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: controller.signal,
    })
    if (!res.ok) throw new Error('请求失败')
    return res.json()
  })()

  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => {
      // Abort the underlying fetch as well as rejecting the deadline race so
      // a fetch implementation that honors AbortController is released.
      controller.abort()
      reject(new Error('请求超时，请稍后重试。'))
    }, MAP_REQUEST_TIMEOUT_MS)
  })

  const races = [request, timeout]
  if (callerSignal) {
    const callerAbort = new Promise((_, reject) => {
      rejectCallerAbort = reject
    })
    callerAbortHandler = () => {
      clearTimeout(timeoutId)
      controller.abort(callerSignal.reason)
      rejectCallerAbort(callerSignal.reason)
    }
    races.push(callerAbort)
    if (callerSignal.aborted) {
      callerAbortHandler()
    } else {
      callerSignal.addEventListener('abort', callerAbortHandler, { once: true })
    }
  }

  try {
    return await Promise.race(races)
  } finally {
    clearTimeout(timeoutId)
    if (callerSignal && callerAbortHandler) {
      callerSignal.removeEventListener('abort', callerAbortHandler)
    }
  }
}

export default function BaiduMapPickerModal({ open, initialLocation, onClose, onConfirm }) {
  const mapContainerRef = useRef(null)
  const mapRef = useRef(null)
  const markerRef = useRef(null)
  const openRef = useRef(open)
  const reverseGenerationRef = useRef(0)
  const searchGenerationRef = useRef(0)
  const searchLoadingRef = useRef(false)
  const pendingRequestControllersRef = useRef(new Set())
  const closeButtonRef = useRef(null)
  const titleId = useId()

  // Keep async callbacks from writing after a close has been rendered, even
  // before the close effect gets a chance to run.
  openRef.current = open

  const [draft, setDraft] = useState(null)
  const [reverseLoading, setReverseLoading] = useState(false)

  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState('')

  const abortPendingRequests = useCallback(() => {
    for (const controller of pendingRequestControllersRef.current) {
      controller.abort()
    }
    pendingRequestControllersRef.current.clear()
  }, [])

  const fetchModalJson = useCallback((url) => {
    const controller = new AbortController()
    pendingRequestControllersRef.current.add(controller)
    return fetchJson(url, { signal: controller.signal }).finally(() => {
      pendingRequestControllersRef.current.delete(controller)
    })
  }, [])

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
    const resizeTimer = setTimeout(() => map.invalidateSize(), 100)

    return () => {
      clearTimeout(resizeTimer)
      map.remove()
      if (mapRef.current === map) {
        mapRef.current = null
        markerRef.current = null
      }
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  // Reset modal state on close; map resources are owned by the initialization
  // effect above so its cleanup also handles parent/router unmounts.
  useEffect(() => {
    // The previous effect cleanup runs during a close -> reopen transition;
    // restore the current open state in this setup before accepting events.
    openRef.current = open

    if (!open) {
      reverseGenerationRef.current += 1
      searchGenerationRef.current += 1
      searchLoadingRef.current = false
      abortPendingRequests()
      markerRef.current = null
      setDraft(null)
      setReverseLoading(false)
      setSearchQuery('')
      setSearchResults([])
      setSearchLoading(false)
      setSearchError('')
    }

    return () => {
      openRef.current = false
      reverseGenerationRef.current += 1
      searchGenerationRef.current += 1
      searchLoadingRef.current = false
      abortPendingRequests()
    }
  }, [abortPendingRequests, open])

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
    const generation = reverseGenerationRef.current + 1
    reverseGenerationRef.current = generation
    if (!openRef.current) return

    const isCurrent = () =>
      openRef.current && reverseGenerationRef.current === generation

    setReverseLoading(true)
    try {
      const data = await fetchModalJson(
        `${REVERSE_GEOCODE_URL}?lat=${lat}&lng=${lng}`
      )
      if (!isCurrent()) return
      const address = data?.data?.address || '未解析到详细地址'
      setDraft((prev) =>
        isCurrent() &&
        prev &&
        prev.latitude === String(lat) &&
        prev.longitude === String(lng)
          ? { ...prev, address }
          : prev
      )
    } catch {
      if (!isCurrent()) return
      setDraft((prev) =>
        isCurrent() &&
        prev &&
        prev.latitude === String(lat) &&
        prev.longitude === String(lng)
          ? { ...prev, address: '未解析到详细地址' }
          : prev
      )
    } finally {
      if (isCurrent()) setReverseLoading(false)
    }
  }, [fetchModalJson])

  const handleSearch = useCallback(async () => {
    const q = searchQuery.trim()
    if (!q || !openRef.current || searchLoadingRef.current) return

    const generation = searchGenerationRef.current + 1
    searchGenerationRef.current = generation
    searchLoadingRef.current = true

    const isCurrent = () =>
      openRef.current && searchGenerationRef.current === generation

    setSearchLoading(true)
    setSearchError('')
    setSearchResults([])
    try {
      const data = await fetchModalJson(
        `${PLACE_SEARCH_URL}?query=${encodeURIComponent(q)}`
      )
      if (!isCurrent()) return
      const results = data?.data?.results || []
      if (results.length === 0) {
        setSearchError('未找到相关地点')
      } else {
        setSearchResults(results)
      }
    } catch {
      if (isCurrent()) setSearchError('搜索失败，请稍后重试')
    } finally {
      if (isCurrent()) {
        searchLoadingRef.current = false
        setSearchLoading(false)
      }
    }
  }, [fetchModalJson, searchQuery])

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

  // Land keyboard focus inside the dialog when it opens, keep Tab inside it,
  // close on Escape and hand focus back to the opener when it closes.
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const dialogRef = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const opener = document.activeElement
    closeButtonRef.current?.focus()
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        onCloseRef.current?.()
        return
      }
      if (event.key !== 'Tab' || !dialogRef.current) return
      const focusable = Array.from(dialogRef.current.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      ))
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const inside = dialogRef.current.contains(document.activeElement)
      if (event.shiftKey && (!inside || document.activeElement === first)) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (!inside || document.activeElement === last)) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      if (opener && typeof opener.focus === 'function' && document.contains(opener)) opener.focus()
    }
  }, [open])

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
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[rgb(12_18_28/0.45)] sm:items-center sm:p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="ui-index-card relative flex h-[92dvh] w-full max-w-4xl flex-col overflow-hidden rounded-b-none sm:h-[85vh] sm:rounded-b-[10px]"
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3 sm:px-5">
          <h2 id={titleId} className="font-display min-w-0 text-base font-bold text-text">地图选点</h2>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="关闭地图选点"
            className="ui-btn-ghost ui-btn-icon"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        {/* Body */}
        <div className="flex min-h-0 flex-1 flex-col md:flex-row">
          {/* Left panel: search + results + preview */}
          <div className="flex max-h-[45%] w-full flex-col border-b border-border md:max-h-none md:w-80 md:border-b-0 md:border-r">
            {/* Search */}
            <div className="border-b border-border-subtle p-3 sm:p-4">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={handleSearchKeyDown}
                  placeholder="搜索地点名称..."
                  aria-label="搜索地点名称"
                  className="ui-field"
                />
                <button
                  type="button"
                  onClick={handleSearch}
                  disabled={searchLoading || !searchQuery.trim()}
                  aria-label="搜索地点"
                  className="ui-btn-primary ui-btn-icon"
                >
                  {searchLoading ? (
                    <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden="true" />
                  ) : (
                    <Search className="h-4 w-4" aria-hidden="true" />
                  )}
                </button>
              </div>
              {searchError && (
                <p role="status" className="mt-2 text-xs font-medium text-danger">{searchError}</p>
              )}
            </div>

            {/* Search results */}
            {searchResults.length > 0 && (
              <ul className="min-h-0 flex-1 divide-y divide-border-subtle overflow-y-auto">
                {searchResults.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => selectCandidate(c)}
                      className="w-full px-4 py-2.5 text-left hover:bg-surface-hover focus-visible:ring-inset"
                    >
                      <span className="block text-sm font-semibold text-text">
                        {c.name || c.address}
                      </span>
                      {c.address && (
                        <span className="mt-0.5 block text-xs text-text-muted">
                          {c.address}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {/* Preview */}
            {draft && (
              <div className="mt-auto border-t border-border-subtle bg-surface-hover/60 p-4">
                <p className="catalog-label mb-1">
                  当前选点 {draft.source ? `(${draft.source})` : ''}
                </p>
                <p className="text-sm text-text">
                  {reverseLoading ? (
                    <span className="flex items-center gap-1 text-text-muted">
                      <Loader2 className="h-3 w-3 motion-safe:animate-spin" aria-hidden="true" /> 解析地址中...
                    </span>
                  ) : (
                    draft.address || '未解析到详细地址'
                  )}
                </p>
                <p className="font-code mt-1 text-xs text-text-muted">
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
          <div className="relative min-h-[240px] flex-1">
            <div ref={mapContainerRef} className="h-full w-full" />
            {!draft && (
              <div className="pointer-events-none absolute bottom-4 left-1/2 z-[1000] -translate-x-1/2 rounded-md bg-[rgb(12_18_28/0.75)] px-3 py-2 text-xs text-white">
                点击地图或搜索地点来选取位置
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3 sm:px-5">
          <button
            type="button"
            onClick={onClose}
            className="ui-btn-secondary"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={!draft}
            className="ui-btn-primary"
          >
            确认选点
          </button>
        </div>
      </div>
    </div>
  )
}
