import { useEffect, useMemo, useRef, useState } from 'react'
import { CARD, getChapterId, getChapterTitle, getCourseId, getCourseName } from '../utils'


const BADGE = 'shrink-0 rounded-full px-2 py-0.5 text-xs'


// Radio list for "study this course up to which chapter". The chosen chapter is
// inclusive; everything after it is left alone.
function ChapterLimitPicker({ courseId, courseName, chapterList, limitId, limitIndex, onChange }) {
  const radioName = `chapter-limit-${courseId}`

  return (
    <fieldset className="mt-2 text-sm">
      <legend className="sr-only">{courseName} 学到哪一节</legend>
      <p className="mb-2 text-xs text-text-muted">选一节作为终点：只学到这一节（含），后面的章节不学。</p>
      <div className="max-h-72 space-y-1 overflow-y-auto pr-1">
        <label className="flex min-h-[44px] cursor-pointer items-center gap-3 rounded-lg bg-surface px-3 py-2">
          <input
            type="radio"
            className="h-4 w-4 shrink-0"
            name={radioName}
            checked={!limitId}
            onChange={() => onChange(courseId, '')}
          />
          <span className="flex-1 font-medium text-text">全部章节</span>
        </label>
        {chapterList.map((chapter, index) => {
          const chapterId = getChapterId(chapter)
          const skipped = limitIndex >= 0 && index > limitIndex
          return (
            <label
              key={`${courseId}-${chapterId || index}`}
              className={[
                'flex min-h-[44px] items-center gap-3 rounded-lg px-3 py-2',
                chapterId ? 'cursor-pointer' : 'cursor-not-allowed',
                chapterId && chapterId === limitId ? 'bg-cta/10 ring-1 ring-cta/40' : 'bg-surface',
                skipped ? 'opacity-50' : '',
              ].join(' ')}
            >
              <input
                type="radio"
                className="h-4 w-4 shrink-0"
                name={radioName}
                disabled={!chapterId}
                checked={Boolean(chapterId) && chapterId === limitId}
                onChange={() => onChange(courseId, chapterId)}
              />
              <span className="w-7 shrink-0 text-right text-xs tabular-nums text-text-muted">{index + 1}.</span>
              <span className="min-w-0 flex-1 text-text/80">{getChapterTitle(chapter)}</span>
              {chapter?.has_finished && <span className={`${BADGE} bg-success-surface text-success`}>已完成</span>}
              {chapter?.need_unlock && <span className={`${BADGE} bg-warning-surface text-warning`}>待解锁</span>}
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
    <p className="mt-1 truncate text-xs text-cta" title={text}>{text}</p>
  )
}


export default function CourseListSection({
  courses, selectedCourses, setSelectedCourses, chapters, expanded,
  toggleExpand, loadCourses, chapterLimits = {}, setChapterLimit = () => {},
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
    <section className={CARD}>


      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">


        <h2 className="text-xl font-semibold text-text">课程列表</h2>


        <div className="flex gap-2">


          <button


            type="button"


            className="min-h-[44px] cursor-pointer rounded-lg border border-border px-3 text-sm"


            onClick={() => setSelectedCourses(allSelected ? [] : courseIds)}


          >


            {allSelected ? '取消全选' : '全选课程'}


          </button>


          <button


            type="button"


            className="min-h-[44px] cursor-pointer rounded-lg border border-border px-3 text-sm"
            disabled={refreshing}
            aria-busy={refreshing}


            onClick={() => {


              void handleRefresh()


            }}


          >


            {refreshing ? '刷新中...' : '刷新课程'}


          </button>


        </div>


      </div>


      <div className="max-h-[36rem] space-y-2 overflow-y-auto">


        {courses.map((course) => {


          const courseId = getCourseId(course)


          const isExpanded = expanded.has(courseId)
          const chapterList = chapters[courseId] || []
          const limitId = chapterLimits[courseId] || ''
          const limitIndex = limitId ? chapterList.findIndex((chapter) => getChapterId(chapter) === limitId) : -1


          return (


            <div key={courseId || Math.random()} className="rounded-xl border border-border/30 bg-surface/60 p-3">


              <div className="flex items-center gap-3">


                <input


                  type="checkbox"


                  className="h-5 w-5"


                  checked={selectedCourses.includes(courseId)}


                  onChange={() => {


                    setSelectedCourses((prev) =>


                      prev.includes(courseId) ? prev.filter((id) => id !== courseId) : [...prev, courseId]


                    )


                  }}


                />


                <div className="min-w-0 flex-1">


                  <p className="font-semibold text-text">{getCourseName(course)}</p>


                  <p className="text-xs text-text-muted">{courseId || '--'}</p>


                  <ChapterLimitSummary chapterList={chapterList} limitId={limitId} limitIndex={limitIndex} />


                </div>


                <button


                  type="button"


                  className="min-h-[44px] min-w-[44px] shrink-0 cursor-pointer rounded-lg border border-border px-2 text-sm"
                  aria-expanded={isExpanded}


                  onClick={() => {


                    void toggleExpand(course)


                  }}


                >


                  {isExpanded ? '收起' : '选章节'}


                </button>


              </div>


              {isExpanded && (chapterList.length > 0 ? (
                <ChapterLimitPicker
                  courseId={courseId}
                  courseName={getCourseName(course)}
                  chapterList={chapterList}
                  limitId={limitId}
                  limitIndex={limitIndex}
                  onChange={setChapterLimit}
                />
              ) : (
                <div className="mt-2 text-xs text-text-muted">暂无章节数据</div>
              ))}


            </div>


          )


        })}


      </div>


    </section>
  )


}
