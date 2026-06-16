import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BookOpen, ClipboardList, ExternalLink, FileText, ListChecks, Loader2, MessageSquare, RefreshCw } from 'lucide-react'
import { api, ApiError } from '../../../utils/api'
import { safeHref } from '../../../utils/safeUrl'
import { CARD, getCourseId, getCourseName } from '../utils'

// Chaoxing course portal tabs.
//
// IMPORTANT: course data is fetched THROUGH our own backend, never by the
// browser directly. The backend holds the user's authenticated Chaoxing
// session and proxies the request server-side. A direct browser fetch to
// chaoxing.com cannot work: chaoxing sends no CORS headers, and the browser
// will not attach the user's chaoxing.com login cookies on a cross-site
// request — so the response is unreadable and/or unauthenticated.
const TABS = [
  { key: 'activities', label: '活动' },
  { key: 'chapters', label: '章节' },
  { key: 'discussions', label: '讨论' },
  { key: 'resources', label: '资料' },
  { key: 'wrong_set', label: '错题集' },
  { key: 'learning_record', label: '学习记录' },
  { key: 'homework', label: '作业' },
  { key: 'tests', label: '考试' },
]

const TAB_ICONS = {
  activities: ClipboardList,
  chapters: BookOpen,
  discussions: MessageSquare,
  resources: FileText,
  homework: ListChecks,
  tests: ListChecks,
}

const STATUS_LABELS = {
  active: '进行中',
  ended: '已结束',
}

const tabLabel = (key) => TABS.find((tab) => tab.key === key)?.label || key

const itemTitle = (item) =>
  item?.title || item?.name || item?.text || item?.label || (item?.id ? `#${item.id}` : '未命名')

export default function CoursePortalSection({ courses, selectedCourses, setError, setNotice }) {
  const courseOptions = useMemo(
    () =>
      (courses || [])
        .map((course) => ({ id: getCourseId(course), name: getCourseName(course) }))
        .filter((course) => course.id),
    [courses]
  )

  const [activeCourseId, setActiveCourseId] = useState('')
  const [activeTab, setActiveTab] = useState('activities')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')

  // Out-of-order response guard (F66): every load bumps this token and remembers
  // its (courseId, tabKey). A resolution whose token is stale — because the user
  // already switched tab/course — is dropped, so a slow earlier request can never
  // overwrite the state of a newer one (header/body mismatch).
  const requestSeqRef = useRef(0)
  const activeRequestRef = useRef({ seq: 0, courseId: '', tabKey: '' })

  const preferredCourseId =
    selectedCourses?.find((id) => courseOptions.some((course) => course.id === id)) ||
    courseOptions[0]?.id ||
    ''

  useEffect(() => {
    if (!activeCourseId || !courseOptions.some((course) => course.id === activeCourseId)) {
      setActiveCourseId(preferredCourseId)
    }
  }, [activeCourseId, courseOptions, preferredCourseId])

  const loadTab = useCallback(
    async (courseId, tabKey) => {
      if (!courseId || !tabKey) return
      const seq = requestSeqRef.current + 1
      requestSeqRef.current = seq
      activeRequestRef.current = { seq, courseId, tabKey }
      // A resolution is "current" only if no newer load was started AND the
      // (courseId, tabKey) it was issued for still matches the active selection.
      const isCurrent = () => {
        const active = activeRequestRef.current
        return active.seq === seq && active.courseId === courseId && active.tabKey === tabKey
      }
      setLoading(true)
      setLoadError('')
      try {
        const payload = await api(
          `/course/chaoxing/course/${encodeURIComponent(courseId)}/tabs/${encodeURIComponent(tabKey)}`
        )
        if (!isCurrent()) return
        const data = payload?.data || payload || {}
        const items = Array.isArray(data.items) ? data.items : []
        // Shell-only tabs (讨论/错题集/学习记录) carry no top-level url; the backend
        // still computes a course shell URL under data.tab.shellUrl so the
        // "open in Chaoxing" link can be restored (F67). All URLs are sanitized to
        // http(s) before they ever reach an <a href> (F33).
        const remoteUrl = safeHref(
          data.url || data.remoteUrl || data.tab?.shellUrl || data.tab?.remoteUrl || ''
        )
        setResult({
          tabKey,
          items,
          remoteUrl,
          message: data.message || '',
        })
        setNotice?.(`已通过后端加载学习通「${tabLabel(tabKey)}」：${items.length} 条`)
      } catch (err) {
        if (!isCurrent()) return
        const message =
          err instanceof ApiError
            ? err.message
            : err?.message || '加载学习通课程数据失败。'
        setResult(null)
        setLoadError(message)
        setError?.(message)
      } finally {
        if (isCurrent()) setLoading(false)
      }
    },
    [setError, setNotice]
  )

  useEffect(() => {
    if (!activeCourseId) return
    void loadTab(activeCourseId, activeTab)
  }, [activeCourseId, activeTab, loadTab])

  if (courseOptions.length === 0) return null

  const items = result?.items || []

  return (
    <section className={CARD}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-text">学习通课程接口</h2>
          <p className="mt-1 text-xs text-text-muted">
            数据由后端携带你的学习通登录态请求，浏览器不直接访问学习通，避免 CORS 与跨站登录态限制
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="min-h-[44px] rounded-lg border border-border bg-surface px-3 text-sm text-text/80"
            value={activeCourseId}
            onChange={(event) => setActiveCourseId(event.target.value)}
          >
            {courseOptions.map((course) => (
              <option key={course.id} value={course.id}>
                {course.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="inline-flex min-h-[44px] min-w-[44px] cursor-pointer items-center justify-center rounded-lg border border-border px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60"
            onClick={() => {
              void loadTab(activeCourseId, activeTab)
            }}
            disabled={loading || !activeCourseId}
            title="刷新"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
        </div>
      </div>

      <div className="flex gap-2 overflow-x-auto pb-2">
        {TABS.map((tab) => {
          const Icon = TAB_ICONS[tab.key] || FileText
          const selected = tab.key === activeTab
          return (
            <button
              key={tab.key}
              type="button"
              className={[
                'inline-flex min-h-[44px] min-w-[72px] shrink-0 cursor-pointer items-center justify-center gap-2 rounded-lg border px-3 text-sm transition-colors',
                selected ? 'border-primary/40 bg-primary/10 text-primary' : 'border-border bg-surface text-text/70'
              ].join(' ')}
              onClick={() => setActiveTab(tab.key)}
              title={tab.label}
            >
              <Icon className="h-4 w-4" />
              <span>{tab.label}</span>
            </button>
          )
        })}
      </div>

      <div className="mt-4 rounded-xl border border-border bg-surface p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <p className="font-semibold text-text">
            {tabLabel(activeTab)}
            {!loading && result ? <span className="ml-2 text-xs font-normal text-text-muted">{items.length} 条</span> : null}
          </p>
          {result?.remoteUrl && (
            <a
              className="inline-flex min-h-[36px] items-center gap-1 rounded-lg border border-border px-3 text-xs text-text/80"
              href={result.remoteUrl}
              target="_blank"
              rel="noreferrer"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              在学习通打开
            </a>
          )}
        </div>

        {loading ? (
          <div className="flex min-h-[120px] items-center justify-center text-sm text-text-muted">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            加载中
          </div>
        ) : loadError ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-3 text-sm text-rose-600">
            {loadError}
          </div>
        ) : items.length > 0 ? (
          <ul className="divide-y divide-slate-100">
            {items.map((item, index) => (
              <li key={item?.id ?? index} className="flex items-start justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <p className="truncate text-sm text-text">{itemTitle(item)}</p>
                  {item?.text && item.text !== itemTitle(item) && (
                    <p className="mt-0.5 truncate text-xs text-text-muted">{item.text}</p>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {item?.status && STATUS_LABELS[item.status] && (
                    <span
                      className={[
                        'rounded px-1.5 py-0.5 text-[11px]',
                        item.status === 'active' ? 'bg-success-surface text-success' : 'bg-surface-hover text-text-muted'
                      ].join(' ')}
                    >
                      {STATUS_LABELS[item.status]}
                    </span>
                  )}
                  {safeHref(item?.url) && (
                    <a
                      className="inline-flex items-center gap-1 text-xs text-primary"
                      href={safeHref(item.url)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                      打开
                    </a>
                  )}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="rounded-lg border border-border-subtle bg-surface-hover px-3 py-8 text-center text-sm text-text-muted">
            {result?.message || '该标签暂无内容。'}
          </div>
        )}
      </div>
    </section>
  )
}
