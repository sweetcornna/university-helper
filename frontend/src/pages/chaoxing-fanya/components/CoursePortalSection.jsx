/* eslint-disable react/prop-types */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { BookOpen, ClipboardList, ExternalLink, FileText, ListChecks, Loader2, RefreshCw } from 'lucide-react'
import { CARD, getCourseId, getCourseName, normalizeCourseText } from '../utils'

const ACTIVE_API_URL = 'https://mobilelearn.chaoxing.com/v2/apis/active/student/activelist'
const ACTIVE_PAGE_URL = 'https://mobilelearn.chaoxing.com/page/active/stuActiveList'
const COURSE_SHELL_URL = 'https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/stu'
const CHAPTER_LIST_URL = 'https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse'
const RESOURCE_LIST_URL = 'https://mooc2-ans.chaoxing.com/mooc2-ans/coursedata/stu-datalist'
const HOMEWORK_LIST_URL = 'https://mooc1.chaoxing.com/mooc2/work/list'
const EXAM_LIST_URL = 'https://mooc1.chaoxing.com/exam-ans/mooc2/exam/exam-list'

const FALLBACK_TABS = [
  { key: 'activities', label: '活动', pageHeader: 0, itemKey: 'activities', fetchKind: 'api' },
  { key: 'chapters', label: '章节', pageHeader: 1, itemKey: 'chapters', fetchKind: 'html' },
  { key: 'discussions', label: '讨论', pageHeader: 2, itemKey: 'items', fetchKind: 'shell' },
  { key: 'resources', label: '资料', pageHeader: 3, itemKey: 'resources', fetchKind: 'html' },
  { key: 'wrong_set', label: '错题集', pageHeader: 4, itemKey: 'items', fetchKind: 'shell' },
  { key: 'learning_record', label: '学习记录', pageHeader: 6, itemKey: 'items', fetchKind: 'shell' },
  { key: 'homework', label: '作业', pageHeader: 8, itemKey: 'homework', fetchKind: 'html' },
  { key: 'tests', label: '考试', pageHeader: 9, itemKey: 'tests', fetchKind: 'html' }
]

const TAB_ICONS = {
  activities: ClipboardList,
  chapters: BookOpen,
  resources: FileText,
  homework: ListChecks,
  tests: ListChecks
}

const buildUrl = (baseUrl, params) => {
  const query = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    query.set(key, String(value))
  })
  const text = query.toString()
  return text ? `${baseUrl}?${text}` : baseUrl
}

const splitSelector = (selector) => {
  const parts = normalizeCourseText(selector).split('_').filter(Boolean)
  return {
    courseId: parts[0] || '',
    classId: parts[1] || '',
    cpi: parts[2] || '',
  }
}

const pickCourseValue = (course, keys) => {
  for (const key of keys) {
    const value = normalizeCourseText(course?.[key])
    if (value) return value
  }
  return ''
}

const buildCourseContext = (course) => {
  const selector = getCourseId(course)
  const parsed = splitSelector(selector)
  const courseId = pickCourseValue(course, ['courseId', 'course_id', 'rawCourseId']) || parsed.courseId
  const classId = pickCourseValue(course, ['classId', 'clazzId', 'class_id', 'clazz_id']) || parsed.classId
  const cpi = pickCourseValue(course, ['cpi', 'cpiId']) || parsed.cpi
  const name = getCourseName(course)
  const fid = pickCourseValue(course, ['fid', 'schoolId', 'school_id']) || '0'
  const stuenc = pickCourseValue(course, ['stuenc', 'stuEnc', 'studentEnc'])
  const enc = pickCourseValue(course, ['enc']) || stuenc
  const openc = pickCourseValue(course, ['openc', 'openC'])
  return { selector, courseId, classId, cpi, name, fid, stuenc, enc, openc }
}

const buildShellUrl = (context, pageHeader) => buildUrl(COURSE_SHELL_URL, {
  courseid: context.courseId,
  clazzid: context.classId,
  cpi: context.cpi,
  enc: context.enc,
  t: Date.now(),
  pageHeader,
  v: 2,
  hideHead: 0,
})

const buildRemoteRequest = (url) => ({
  method: 'GET',
  url,
  credentials: 'include',
  mode: 'cors',
  requiresChaoxingLogin: true,
})

const buildRemoteTab = (context, tab) => {
  const common = {
    ...tab,
    itemKey: tab.itemKey || 'items',
    fetchKind: tab.fetchKind || 'html',
    fetchable: true,
    supported: true,
    remoteSource: 'chaoxing',
    directBrowserRequest: true,
    browserRequestMode: 'remote-direct',
    shellUrl: buildShellUrl(context, tab.pageHeader),
  }

  let remoteUrl = ''
  let remoteApiUrl = ''
  if (tab.key === 'activities') {
    remoteUrl = buildUrl(ACTIVE_PAGE_URL, {
      courseid: context.courseId,
      clazzid: context.classId,
      cpi: context.cpi,
      ut: 's',
      t: Date.now(),
      stuenc: context.stuenc,
      fid: context.fid,
    })
    remoteApiUrl = buildUrl(ACTIVE_API_URL, {
      fid: context.fid,
      courseId: context.courseId,
      classId: context.classId,
      _: Date.now(),
    })
  }
  if (tab.key === 'chapters') {
    remoteUrl = buildUrl(CHAPTER_LIST_URL, {
      courseid: context.courseId,
      clazzid: context.classId,
      cpi: context.cpi,
      ut: 's',
      t: Date.now(),
      stuenc: context.stuenc,
    })
  }
  if (tab.key === 'resources') {
    remoteUrl = buildUrl(RESOURCE_LIST_URL, {
      courseid: context.courseId,
      clazzid: context.classId,
      cpi: context.cpi,
      ut: 's',
      t: Date.now(),
      stuenc: context.stuenc,
    })
  }
  if (tab.key === 'homework') {
    remoteUrl = buildUrl(HOMEWORK_LIST_URL, {
      courseid: context.courseId,
      clazzid: context.classId,
      cpi: context.cpi,
      ut: 's',
      t: Date.now(),
      stuenc: context.stuenc,
    })
  }
  if (tab.key === 'tests') {
    remoteUrl = buildUrl(EXAM_LIST_URL, {
      courseid: context.courseId,
      clazzid: context.classId,
      cpi: context.cpi,
      ut: 's',
      t: Date.now(),
      stuenc: context.stuenc,
      enc: context.enc,
      openc: context.openc,
    })
  }

  const requestUrl = remoteApiUrl || remoteUrl || common.shellUrl
  return {
    ...common,
    ...(remoteUrl ? { remoteUrl, frameUrl: remoteUrl } : {}),
    ...(remoteApiUrl ? { remoteApiUrl } : {}),
    remoteRequest: buildRemoteRequest(requestUrl),
  }
}

const buildRemotePortal = (course) => {
  const context = buildCourseContext(course)
  return {
    course: {
      id: context.selector,
      courseId: context.courseId,
      classId: context.classId,
      cpi: context.cpi,
      name: context.name,
      courseName: context.name,
      fid: context.fid,
      stuenc: context.stuenc,
      enc: context.enc,
      openc: context.openc,
    },
    tabs: FALLBACK_TABS.map((tab) => buildRemoteTab(context, tab)),
  }
}

const getRemoteRequestUrl = (tab) => {
  return tab?.remoteRequest?.url || tab?.remoteApiUrl || tab?.remoteUrl || tab?.shellUrl || ''
}

export default function CoursePortalSection({ courses, selectedCourses, setError, setNotice }) {
  const courseOptions = useMemo(
    () =>
      courses
        .map((course) => ({
          id: getCourseId(course),
          name: getCourseName(course),
          raw: course,
        }))
        .filter((course) => course.id),
    [courses]
  )

  const [activeCourseId, setActiveCourseId] = useState('')
  const [activeTab, setActiveTab] = useState('activities')
  const [portal, setPortal] = useState(null)
  const [loading, setLoading] = useState(false)
  const [remoteLoading, setRemoteLoading] = useState(false)
  const [remoteResult, setRemoteResult] = useState(null)

  const preferredCourseId = selectedCourses.find((id) => courseOptions.some((course) => course.id === id)) || courseOptions[0]?.id || ''
  const activeCourse = courseOptions.find((course) => course.id === activeCourseId)?.raw || null

  useEffect(() => {
    if (!activeCourseId || !courseOptions.some((course) => course.id === activeCourseId)) {
      setActiveCourseId(preferredCourseId)
    }
  }, [activeCourseId, courseOptions, preferredCourseId])

  const tabs = portal?.tabs?.length ? portal.tabs : FALLBACK_TABS
  const activePortalTab = tabs.find((tab) => tab.key === activeTab) || tabs[0]
  const activeRemoteUrl = getRemoteRequestUrl(activePortalTab)

  const loadPortal = useCallback(async () => {
    if (!activeCourse) return

    setLoading(true)
    try {
      setPortal(buildRemotePortal(activeCourse))
      setRemoteResult(null)
      setNotice?.('学习通远程地址已更新。')
    } catch (err) {
      setError?.(err?.message || '请求学习通远程接口失败。')
    } finally {
      setLoading(false)
    }
  }, [activeCourse, setError, setNotice])

  const requestRemoteEndpoint = useCallback(async () => {
    const requestUrl = getRemoteRequestUrl(activePortalTab)
    if (!requestUrl) {
      setRemoteResult({ ok: false, message: '当前标签没有学习通远程地址。' })
      return
    }

    setRemoteLoading(true)
    setRemoteResult(null)
    try {
      const response = await fetch(requestUrl, {
        method: activePortalTab?.remoteRequest?.method || 'GET',
        credentials: 'include',
        mode: activePortalTab?.remoteRequest?.mode || 'cors',
      })
      const text = await response.text()
      setRemoteResult({
        ok: response.ok,
        status: response.status,
        url: requestUrl,
        contentType: response.headers.get('content-type') || '',
        preview: text.slice(0, 1000),
      })
      setNotice?.(`学习通远程接口已请求：HTTP ${response.status}`)
    } catch (err) {
      setRemoteResult({
        ok: false,
        status: 'blocked',
        url: requestUrl,
        message: err?.message || '浏览器无法读取学习通远程响应。',
      })
      setError?.('已使用学习通远程地址发起请求，但浏览器可能因学习通 CORS 或登录态限制无法读取响应。')
    } finally {
      setRemoteLoading(false)
    }
  }, [activePortalTab, setError, setNotice])

  useEffect(() => {
    if (!activeCourseId) return
    void loadPortal()
  }, [activeCourseId, loadPortal])

  if (courseOptions.length === 0) return null

  return (
    <section className={CARD}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">学习通远程接口</h2>
          <p className="mt-1 text-xs text-slate-500">主接口为学习通真实远程域名，网页端可直接打开或发起请求</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="min-h-[44px] rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700"
            value={activeCourseId}
            onChange={(event) => {
              setPortal(null)
              setActiveCourseId(event.target.value)
            }}
          >
            {courseOptions.map((course) => (
              <option key={course.id} value={course.id}>
                {course.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="inline-flex min-h-[44px] min-w-[44px] cursor-pointer items-center justify-center rounded-lg border border-slate-200 px-3 text-sm"
            onClick={() => {
              void loadPortal()
            }}
            disabled={loading}
            title="刷新"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
        </div>
      </div>

      <div className="flex gap-2 overflow-x-auto pb-2">
        {tabs.map((tab) => {
          const Icon = TAB_ICONS[tab.key] || FileText
          const selected = tab.key === activeTab
          return (
            <button
              key={tab.key}
              type="button"
              className={[
                'inline-flex min-h-[44px] min-w-[72px] shrink-0 cursor-pointer items-center justify-center gap-2 rounded-lg border px-3 text-sm transition-colors',
                selected ? 'border-sky-200 bg-sky-50 text-sky-700' : 'border-slate-200 bg-white text-slate-600'
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

      <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="font-semibold text-slate-900">{activePortalTab?.label || '学习通接口'}</p>
            <p className="mt-1 break-all font-mono text-xs text-slate-500">{activeRemoteUrl || '暂无学习通远程地址'}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {activeRemoteUrl && (
              <button
                type="button"
                className="inline-flex min-h-[36px] items-center gap-1 rounded-lg border border-sky-200 bg-sky-50 px-3 text-xs text-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
                onClick={() => {
                  void requestRemoteEndpoint()
                }}
                disabled={remoteLoading}
              >
                {remoteLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                直连请求
              </button>
            )}
            {activeRemoteUrl && (
              <a
                className="inline-flex min-h-[36px] items-center gap-1 rounded-lg border border-slate-200 px-3 text-xs text-slate-700"
                href={activeRemoteUrl}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                学习通远程地址
              </a>
            )}
          </div>
        </div>

        {remoteResult && (
          <div
            className={[
              'mb-3 rounded-lg border px-3 py-2 text-xs',
              remoteResult.ok ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'
            ].join(' ')}
          >
            <p className="font-medium">
              远程请求：{remoteResult.status || '--'} {remoteResult.contentType ? ` / ${remoteResult.contentType}` : ''}
            </p>
            {remoteResult.message && <p className="mt-1">{remoteResult.message}</p>}
            {remoteResult.preview && (
              <pre className="mt-2 max-h-28 overflow-auto whitespace-pre-wrap break-all rounded bg-white/70 p-2 text-[11px] text-slate-700">
                {remoteResult.preview}
              </pre>
            )}
          </div>
        )}

        {loading ? (
          <div className="flex min-h-[120px] items-center justify-center text-sm text-slate-500">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            加载中
          </div>
        ) : activeRemoteUrl ? (
          <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-8 text-center text-sm text-slate-500">
            默认只使用学习通远程地址。点击“直连请求”读取远程响应，或点击“学习通远程地址”在新窗口打开。
          </div>
        ) : (
          <div className="py-8 text-center text-sm text-slate-500">暂未发现学习通远程接口</div>
        )}
      </div>
    </section>
  )
}
