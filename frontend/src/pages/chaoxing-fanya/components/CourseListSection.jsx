import { useMemo } from 'react'
import { CARD, getCourseId, getCourseName } from '../utils'


export default function CourseListSection({
  courses, selectedCourses, setSelectedCourses, chapters, expanded,
  toggleExpand, loadCourses,
}) {


  const courseIds = useMemo(() => courses.map(getCourseId).filter(Boolean), [courses])


  const allSelected = useMemo(


    () => courseIds.length > 0 && courseIds.length === selectedCourses.length,


    [courseIds.length, selectedCourses.length]


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


            onClick={() => {


              void loadCourses()


            }}


          >


            刷新课程


          </button>


        </div>


      </div>


      <div className="max-h-80 space-y-2 overflow-y-auto">


        {courses.map((course) => {


          const courseId = getCourseId(course)


          const isExpanded = expanded.has(courseId)


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


                <div className="flex-1">


                  <p className="font-semibold text-text">{getCourseName(course)}</p>


                  <p className="text-xs text-text-muted">{courseId || '--'}</p>


                </div>


                <button


                  type="button"


                  className="min-h-[44px] min-w-[44px] cursor-pointer rounded-lg border border-border px-2 text-sm"


                  onClick={() => {


                    void toggleExpand(course)


                  }}


                >


                  {isExpanded ? '收起' : '章节'}


                </button>


              </div>


              {isExpanded && (


                <div className="mt-2 space-y-1 text-sm text-text/70">


                  {(chapters[courseId] || []).map((chapter) => (


                    <div key={`${courseId}-${chapter.id || chapter.name}`} className="rounded-lg bg-surface px-3 py-2">


                      {chapter.title || chapter.name}


                    </div>


                  ))}


                  {(chapters[courseId] || []).length === 0 && (


                    <div className="text-xs text-text-muted">暂无章节数据</div>


                  )}


                </div>


              )}


            </div>


          )


        })}


      </div>


    </section>
  )


}
