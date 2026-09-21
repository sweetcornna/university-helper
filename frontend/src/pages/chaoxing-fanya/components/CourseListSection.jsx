import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { Input } from '../../../components'
import { api } from '../../../utils/api'
import { CARD, getCourseId, getCourseName } from '../utils'


// Above this many courses, only the first group starts open. A normal term is
// 6–12 courses, which still reads fine fully expanded inside this card's own
// scroll area; past ~20 (multi-term archives) the expanded sections rebuild the
// exact wall of rows the grouping exists to break up.
const AUTO_COLLAPSE_THRESHOLD = 20


// Ungrouped courses arrive from the backend in a group id "0" named 我的课程 —
// the same shape we synthesise for the flat-list fallback below.
const UNGROUPED_ID = '0'
const UNGROUPED_NAME = '我的课程'


// Returns null (rather than []) when the payload carries nothing usable, so the
// caller can tell "grouped data unavailable" from "grouped data, no courses".
const normalizeGroups = (rawGroups) => {
  if (!Array.isArray(rawGroups)) return null
  const groups = rawGroups
    .map((group, index) => ({
      id: String(group?.id ?? index),
      name: String(group?.name || '').trim() || UNGROUPED_NAME,
      courses: (Array.isArray(group?.courses) ? group.courses : []).filter((course) =>
        getCourseId(course)
      ),
    }))
    .filter((group) => group.courses.length > 0)
  return groups.length > 0 ? groups : null
}


export default function CourseListSection({
  courses, selectedCourses, setSelectedCourses, chapters, expanded,
  toggleExpand, loadCourses,
}) {

  // `null` means "no grouped data" — either not fetched yet or unavailable —
  // and makes the component fall back to the flat `courses` prop.
  const [groupData, setGroupData] = useState(null)
  const [groupsLoading, setGroupsLoading] = useState(true)
  const [groupNotice, setGroupNotice] = useState('')
  const [query, setQuery] = useState('')
  const [collapsed, setCollapsed] = useState(() => new Set())
  const panelPrefix = useId()

  const loadGroups = useCallback(async () => {
    setGroupsLoading(true)
    try {
      const resp = await api('/chaoxing/courses/grouped')
      const groups = normalizeGroups(resp?.groups ?? resp?.data?.groups)
      setGroupData(groups)
      setGroupNotice('')
    } catch {
      // Fail open: an older backend (404) or any transport failure just means we
      // render the flat list the page already loaded, as a single section.
      setGroupData(null)
      setGroupNotice('暂时无法获取课程分组，已按单个列表显示。')
    } finally {
      setGroupsLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadGroups()
  }, [loadGroups])

  const groups = useMemo(() => {
    if (groupData) return groupData
    const flat = (courses || []).filter((course) => getCourseId(course))
    return flat.length > 0 ? [{ id: UNGROUPED_ID, name: UNGROUPED_NAME, courses: flat }] : []
  }, [courses, groupData])

  const allCourseIds = useMemo(
    () => Array.from(new Set(groups.flatMap((group) => group.courses.map(getCourseId)))),
    [groups]
  )

  // Apply the initial collapse once per loaded group set (keyed by the group
  // ids) so a refresh re-applies it but the user's own toggling is never
  // overwritten by a re-render.
  const groupSignature = groups.map((group) => group.id).join('|')
  const appliedSignatureRef = useRef('')
  useEffect(() => {
    if (!groupSignature || appliedSignatureRef.current === groupSignature) return
    appliedSignatureRef.current = groupSignature
    setCollapsed(
      allCourseIds.length > AUTO_COLLAPSE_THRESHOLD
        ? new Set(groups.slice(1).map((group) => group.id))
        : new Set()
    )
  }, [allCourseIds.length, groupSignature, groups])

  const normalizedQuery = query.trim().toLowerCase()

  const visibleGroups = useMemo(() => {
    if (!normalizedQuery) return groups
    return groups
      .map((group) => ({
        ...group,
        courses: group.courses.filter((course) =>
          getCourseName(course).toLowerCase().includes(normalizedQuery)
        ),
      }))
      .filter((group) => group.courses.length > 0)
  }, [groups, normalizedQuery])

  const selectedSet = useMemo(() => new Set(selectedCourses), [selectedCourses])

  const allSelected = allCourseIds.length > 0 && allCourseIds.every((id) => selectedSet.has(id))

  // The selection model is unchanged: a flat array of getCourseId() strings,
  // which the page posts straight through as /course/start's `course_ids`.
  const toggleCourse = useCallback(
    (courseId) => {
      setSelectedCourses((prev) =>
        prev.includes(courseId) ? prev.filter((id) => id !== courseId) : [...prev, courseId]
      )
    },
    [setSelectedCourses]
  )

  const setGroupSelection = useCallback(
    (groupCourseIds, selectAll) => {
      setSelectedCourses((prev) => {
        if (!selectAll) return prev.filter((id) => !groupCourseIds.includes(id))
        return [...prev, ...groupCourseIds.filter((id) => !prev.includes(id))]
      })
    },
    [setSelectedCourses]
  )

  const toggleGroup = useCallback((groupId) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(groupId)) next.delete(groupId)
      else next.add(groupId)
      return next
    })
  }, [])

  return (
    <section className={CARD}>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">

        <div>
          <h2 className="text-xl font-semibold text-text">课程列表</h2>
          <p className="mt-1 text-xs text-text-muted" role="status">
            共 {allCourseIds.length} 门课程，已选择 {selectedCourses.length} 门
          </p>
        </div>

        <div className="flex gap-2">

          <button
            type="button"
            className="min-h-[44px] cursor-pointer rounded-lg border border-border px-3 text-sm focus-visible:ring-2 focus-visible:ring-primary/40"
            onClick={() => setSelectedCourses(allSelected ? [] : allCourseIds)}
          >
            {allSelected ? '取消全选' : '全选课程'}
          </button>

          <button
            type="button"
            className="min-h-[44px] cursor-pointer rounded-lg border border-border px-3 text-sm focus-visible:ring-2 focus-visible:ring-primary/40"
            onClick={() => {
              void loadCourses()
              void loadGroups()
            }}
          >
            刷新课程
          </button>

        </div>

      </div>

      <div className="mb-4">
        <Input
          id="fanya-course-search"
          label="搜索课程"
          type="search"
          placeholder="输入课程名称筛选"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {groupNotice && (
        <p className="mb-3 text-xs text-text-muted" role="status">
          {groupNotice}
        </p>
      )}

      {groupsLoading && groups.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-text-muted">正在加载课程分组…</p>
      ) : visibleGroups.length === 0 ? (
        <p className="rounded-xl border border-border/30 bg-surface/60 px-4 py-6 text-center text-sm text-text-muted">
          {normalizedQuery
            ? `没有名称包含「${query.trim()}」的课程，换个关键词试试。`
            : '暂无课程，点击「刷新课程」重新获取。'}
        </p>
      ) : (
        <div className="max-h-96 space-y-3 overflow-y-auto">

          {visibleGroups.map((group) => {

            const groupCourseIds = group.courses.map(getCourseId)
            const groupSelectedCount = groupCourseIds.filter((id) => selectedSet.has(id)).length
            const groupAllSelected = groupSelectedCount === groupCourseIds.length
            // A search always reveals its matches, whatever the collapse state.
            const isOpen = Boolean(normalizedQuery) || !collapsed.has(group.id)
            const panelId = `${panelPrefix}-group-${group.id}`

            return (
              <div key={group.id} className="rounded-xl border border-border/30 bg-surface/60">

                <div className="flex flex-wrap items-center gap-2 p-2">

                  <button
                    type="button"
                    aria-expanded={isOpen}
                    aria-controls={panelId}
                    className="flex min-h-[44px] flex-1 cursor-pointer items-center gap-2 rounded-lg px-2 text-left focus-visible:ring-2 focus-visible:ring-primary/40"
                    onClick={() => toggleGroup(group.id)}
                  >
                    <ChevronRight
                      aria-hidden="true"
                      className={`h-4 w-4 shrink-0 text-text-muted transition-transform duration-200 ${isOpen ? 'rotate-90' : ''}`}
                    />
                    <span className="font-semibold text-text">{group.name}</span>
                    <span className="text-xs text-text-muted">
                      {group.courses.length} 门 · 已选 {groupSelectedCount}
                    </span>
                  </button>

                  <button
                    type="button"
                    className="min-h-[44px] cursor-pointer rounded-lg border border-border px-3 text-sm focus-visible:ring-2 focus-visible:ring-primary/40"
                    onClick={() => setGroupSelection(groupCourseIds, !groupAllSelected)}
                  >
                    {groupAllSelected ? '取消全选' : '全选'}
                  </button>

                </div>

                <div id={panelId}>
                  {isOpen && (
                    <div className="space-y-2 px-3 pb-3">

                      {group.courses.map((course) => {

                        const courseId = getCourseId(course)
                        const courseName = getCourseName(course)
                        const isExpanded = expanded.has(courseId)

                        return (
                          <div
                            key={courseId}
                            className="rounded-xl border border-border/30 bg-surface/60 p-3"
                          >

                            <div className="flex items-center gap-3">

                              <input
                                type="checkbox"
                                className="h-5 w-5"
                                aria-label={`选择课程 ${courseName}`}
                                checked={selectedSet.has(courseId)}
                                onChange={() => toggleCourse(courseId)}
                              />

                              <div className="flex-1">
                                <p className="font-semibold text-text">{courseName}</p>
                                <p className="text-xs text-text-muted">{courseId || '--'}</p>
                              </div>

                              <button
                                type="button"
                                aria-expanded={isExpanded}
                                className="min-h-[44px] min-w-[44px] cursor-pointer rounded-lg border border-border px-2 text-sm focus-visible:ring-2 focus-visible:ring-primary/40"
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
                                  <div
                                    key={`${courseId}-${chapter.id || chapter.name}`}
                                    className="rounded-lg bg-surface px-3 py-2"
                                  >
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
                  )}
                </div>

              </div>
            )

          })}

        </div>
      )}

    </section>
  )

}
