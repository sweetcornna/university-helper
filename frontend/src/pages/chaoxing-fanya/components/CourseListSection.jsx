import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, Loader2, RefreshCw } from 'lucide-react'

import { CARD, getChapterId, getChapterTitle, getCourseId, getCourseName } from '../utils'


const BADGE = 'shrink-0 rounded px-1.5 py-0.5 text-[0.6875rem] font-semibold'


// Radio list for "study this course up to which chapter". The chosen chapter is
// inclusive; everything after it is left alone.
function ChapterLimitPicker({ courseId, courseName, chapterList, limitId, limitIndex, onChange }) {
  const radioName = `chapter-limit-${courseId}`

  return (
    <fieldset className="mt-3 border-t border-border-subtle pt-3 text-sm">
      <legend className="sr-only">{courseName} 学到哪一节</legend>
      <p className="mb-2 text-xs text-text-muted">只学到所选一节（含）。</p>
      <div className="max-h-72 divide-y divide-border-subtle overflow-y-auto rounded-md border border-border-subtle bg-surface">
        <label className="flex min-h-[44px] cursor-pointer items-center gap-3 px-3 py-2 hover:bg-surface-hover">
          <input
            type="radio"
            className="ui-check"
            name={radioName}
            checked={!limitId}
            onChange={() => onChange(courseId, '')}
          />
          <span className="flex-1 font-semibold text-text">全部章节</span>
        </label>
        {chapterList.map((chapter, index) => {
          const chapterId = getChapterId(chapter)
          const skipped = limitIndex >= 0 && index > limitIndex
          const chosen = Boolean(chapterId) && chapterId === limitId
          return (
            <label
              key={`${courseId}-${chapterId || index}`}
              className={[
                'flex min-h-[44px] items-center gap-3 px-3 py-2',
                chapterId ? 'cursor-pointer hover:bg-surface-hover' : 'cursor-not-allowed',
                chosen ? 'bg-primary/10' : '',
                skipped ? 'text-text-muted' : '',
              ].join(' ')}
            >
              <input
                type="radio"
                className="ui-check"
                name={radioName}
                disabled={!chapterId}
                checked={chosen}
                onChange={() => onChange(courseId, chapterId)}
              />
              <span className="font-code w-7 shrink-0 text-right text-xs text-text-muted">{index + 1}.</span>
              <span className={`min-w-0 flex-1 ${skipped ? 'line-through decoration-border' : 'text-text'}`}>{getChapterTitle(chapter)}</span>
              {chapter?.has_finished && <span className={`${BADGE} bg-success-surface text-success`}>已完成</span>}
              {chapter?.need_unlock && <span className={`${BADGE} bg-warning-surface text-warning`}>待解锁</span>}
              {chosen && <span className={`${BADGE} bg-primary text-on-primary`}>终点</span>}
              {skipped && <span className={`${BADGE} bg-surface-hover text-text-muted`}>不学</span>}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}

function ChapterLimitSummary({ chapterList, limitId, limitIndex }) {
  if (!limitId) return null
  const text = limitIndex >= 0
    ? `学到 ${limitIndex + 1}/${chapterList.length} 节：${getChapterTitle(chapterList[limitIndex])}`
    : '学到所选章节'
  return (
    <p className="mt-0.5 truncate text-xs font-semibold text-primary" title={text}>{text}</p>
  )
}

function ChapterArea({ course, courseId, chapterList, chapterStatus, limitId, limitIndex, onChange, toggleExpand }) {
  const status = chapterStatus?.[courseId]
  if (status?.loading && chapterList.length === 0) {
    return (
      <p role="status" className="mt-2 flex items-center gap-2 px-1 text-sm text-text-muted">
        <Loader2 className="h-4 w-4 motion-safe:animate-spin text-primary" aria-hidden="true" />正在读取章节…
      </p>
    )
  }
  if (status?.error) {
    return (
      <div role="alert" className="mt-2 flex flex-wrap items-center gap-3 rounded-lg border border-danger/30 bg-danger-surface px-3 py-2 text-sm text-danger">
        <span className="min-w-0 flex-1 break-words">章节没有读出来：{status.error}</span>
        <button type="button" onClick={() => { void toggleExpand(course, { reload: true }) }} className="ui-btn-secondary min-h-[44px] px-3 text-sm">
          重试
        </button>
      </div>
    )
  }
  if (chapterList.length === 0) {
    return <p className="mt-2 px-1 text-sm text-text-muted">这门课没有读到章节，开始后会学完整门课。</p>
  }
  return (
    <ChapterLimitPicker
      courseId={courseId}
      courseName={getCourseName(course)}
      chapterList={chapterList}
      limitId={limitId}
      limitIndex={limitIndex}
      onChange={onChange}
    />
  )
}


export default function CourseListSection({
  courses, selectedCourses, setSelectedCourses, chapters, expanded,
  toggleExpand, loadCourses, chapterLimits = {}, setChapterLimit = () => {},
  chapterStatus = {}, loadError = '',
}) {
  const [refreshing, setRefreshing] = useState(false)
  const refreshInFlightRef = useRef(false)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const handleRefresh = async () => {
    if (refreshInFlightRef.current) return

    refreshInFlightRef.current = true
    setRefreshing(true)
    try {
      await loadCourses()
    } finally {
      refreshInFlightRef.current = false
      if (mountedRef.current) setRefreshing(false)
    }
  }

  const courseIds = useMemo(() => courses.map(getCourseId).filter(Boolean), [courses])

  const allSelected = useMemo(
    () => courseIds.length > 0 && courseIds.every((courseId) => selectedCourses.includes(courseId)),
    [courseIds, selectedCourses]
  )

  return (
    <section aria-labelledby="fanya-course-list-title" className={CARD}>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 id="fanya-course-list-title" className="font-display text-base font-bold text-text">
            课程列表 <span className="font-code text-xs font-normal text-text-muted">{courses.length} 门</span>
          </h2>
        </div>

        <div className="flex gap-2">
          <button
            type="button"
            className="ui-btn-secondary min-h-[44px] px-3 text-sm"
            onClick={() => setSelectedCourses(allSelected ? [] : courseIds)}
          >
            {allSelected ? '取消全选' : '全选课程'}
          </button>

          <button
            type="button"
            className="ui-btn-secondary min-h-[44px] gap-1.5 px-3 text-sm"
            disabled={refreshing}
            aria-busy={refreshing}
            onClick={() => { void handleRefresh() }}
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? 'motion-safe:animate-spin' : ''}`} aria-hidden="true" />
            {refreshing ? '刷新中...' : '刷新课程'}
          </button>
        </div>
      </div>

      {loadError && (
        <p role="alert" className="mb-3 rounded-xl border border-danger/30 bg-danger-surface px-3 py-2.5 text-sm text-danger">
          刷新课程失败：{loadError}。下面是上次读到的课程。
        </p>
      )}

      <ul className="space-y-2">
        {courses.map((course, index) => {
          const courseId = getCourseId(course)
          const courseName = getCourseName(course)
          const isExpanded = expanded.has(courseId)
          const chapterList = chapters[courseId] || []
          const limitId = chapterLimits[courseId] || ''
          const limitIndex = limitId ? chapterList.findIndex((chapter) => getChapterId(chapter) === limitId) : -1
          const checked = selectedCourses.includes(courseId)
          const chapterPanelId = `fanya-chapters-${index}`

          return (
            <li
              key={courseId || `course-${index}`}
              className={`rounded-lg border p-2 transition-colors ${checked ? 'border-primary/50 bg-primary/5' : 'border-border-subtle bg-surface'}`}
            >
              <div className="flex items-center gap-2">
                <label className="flex min-h-[44px] min-w-0 flex-1 cursor-pointer items-center gap-3 rounded-lg px-2">
                  <input
                    type="checkbox"
                    className="ui-check h-5 w-5 shrink-0"
                    checked={checked}
                    disabled={!courseId}
                    onChange={() => {
                      setSelectedCourses((prev) =>
                        prev.includes(courseId) ? prev.filter((id) => id !== courseId) : [...prev, courseId]
                      )
                    }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block break-words font-semibold text-text">{courseName}</span>
                    <ChapterLimitSummary chapterList={chapterList} limitId={limitId} limitIndex={limitIndex} />
                  </span>
                </label>

                <button
                  type="button"
                  className="ui-btn-ghost min-h-[44px] min-w-[44px] shrink-0 px-3 text-sm"
                  disabled={!courseId}
                  aria-expanded={isExpanded}
                  aria-controls={isExpanded ? chapterPanelId : undefined}
                  aria-label={`${isExpanded ? '收起' : '选章节'}：${courseName}`}
                  onClick={() => { void toggleExpand(course) }}
                >
                  {isExpanded ? '收起' : '选章节'}
                  <ChevronDown className={`h-3.5 w-3.5 motion-safe:transition-transform ${isExpanded ? 'rotate-180' : ''}`} aria-hidden="true" />
                </button>
              </div>

              {isExpanded && (
                <div id={chapterPanelId} className="px-1 pb-1">
                  <ChapterArea
                    course={course}
                    courseId={courseId}
                    chapterList={chapterList}
                    chapterStatus={chapterStatus}
                    limitId={limitId}
                    limitIndex={limitIndex}
                    onChange={setChapterLimit}
                    toggleExpand={toggleExpand}
                  />
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
