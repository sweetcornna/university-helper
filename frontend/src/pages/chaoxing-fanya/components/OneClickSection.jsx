import { useCallback, useMemo, useState } from 'react'
import { Loader2, Zap } from 'lucide-react'
import { Button } from '../../../components'
import { CARD, getCourseId } from '../utils'
import { describeAnswerBank } from '../hooks/useTaskPreferences'


// One button that takes the whole run from 0 to 100%: it selects every course,
// then shows what is about to happen so the user confirms once and walks away.
//
// It deliberately does NOT render its own course picker. The grouped list right
// below is already the picker — duplicating it would mean two selection models
// to keep in sync, and the payload is built from the shared `selectedCourses`.
export default function OneClickSection({
  courses,
  selectedCourses,
  setSelectedCourses,
  startTask,
  loading,
  authenticated,
  preferences,
  hasAnswerBank,
  preferencesLoading,
  preferencesError,
}) {
  const [armed, setArmed] = useState(false)

  const allCourseIds = useMemo(
    () => courses.map((course) => getCourseId(course)).filter(Boolean),
    [courses]
  )

  const selectedCount = selectedCourses.length
  const answerBank = describeAnswerBank(preferences, hasAnswerBank)

  const arm = useCallback(() => {
    setSelectedCourses(allCourseIds)
    setArmed(true)
  }, [allCourseIds, setSelectedCourses])

  if (!authenticated) return null

  return (
    <section className={CARD} aria-labelledby="one-click-heading">
      <div className="flex items-start gap-3">
        <Zap className="mt-1 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <h2 id="one-click-heading" className="text-lg font-semibold">
            一键全自动
          </h2>
          <p className="mt-1 text-sm text-text-muted">
            选中全部课程，自动播放课程视频并作答章节测验，一直跑到完成。
          </p>
        </div>
      </div>

      {!armed ? (
        <Button
          type="button"
          variant="primary"
          className="mt-5 w-full"
          onClick={arm}
          disabled={allCourseIds.length === 0}
        >
          {allCourseIds.length === 0 ? '暂无可刷课程' : `一键全自动（${allCourseIds.length} 门课程）`}
        </Button>
      ) : (
        <div className="mt-5 space-y-4">
          <dl className="space-y-2 rounded-xl bg-surface-hover/60 p-4 text-sm">
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-text-muted">本次将处理</dt>
              <dd className="font-medium">{selectedCount} 门课程</dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-text-muted">答题方式</dt>
              <dd className="font-medium">{preferencesLoading ? '读取中…' : answerBank}</dd>
            </div>
          </dl>

          {/* A failed settings read must not be reported as "未配置" — that would
              be stating a fact we do not have. */}
          {preferencesError && (
            <p role="alert" className="rounded-xl bg-warning-surface/60 p-3 text-sm text-warning">
              读取已保存的答题设置失败，本次将使用页面下方的设置。
            </p>
          )}

          {!preferencesLoading && !preferencesError && !hasAnswerBank && (
            <p role="alert" className="rounded-xl bg-warning-surface/60 p-3 text-sm text-warning">
              还没有配置答题模型，现在开始只会播放视频、<strong>不会作答任何题目</strong>。
              请先在下方「答题配置」填写 AI 接口地址、密钥和模型，保存后再开始。
            </p>
          )}

          {selectedCount === 0 && (
            <p role="alert" className="text-sm text-danger">
              课程已全部取消勾选。请在下方课程列表中至少选择一门。
            </p>
          )}

          <div className="flex flex-col gap-3 sm:flex-row">
            <Button
              type="button"
              variant="primary"
              className="inline-flex flex-1 items-center justify-center gap-2"
              onClick={startTask}
              disabled={loading || selectedCount === 0}
              aria-busy={loading}
            >
              {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
              {loading ? '正在启动…' : '确认开始'}
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="sm:w-32"
              onClick={() => setArmed(false)}
              disabled={loading}
            >
              取消
            </Button>
          </div>

          <p className="text-xs text-text-muted">
            已为你勾选全部课程。想跳过某几门，在下方课程列表里取消勾选即可，这里的数量会同步。
          </p>
        </div>
      )}
    </section>
  )
}
