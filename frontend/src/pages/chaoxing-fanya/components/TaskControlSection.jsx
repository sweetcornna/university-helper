import { CARD, DONE_STATUSES, toNum, normalizeCourseText } from '../utils'


export default function TaskControlSection({
  taskId, taskStatus, loading, isRunning, statusText,
  startTask, controlTask,
}) {


  const progress = taskStatus?.progress || {}
  const currentCourseName = normalizeCourseText(progress.current_course)
  const videoProgress = progress.video_progress && typeof progress.video_progress === 'object' ? progress.video_progress : null
  const videoCurrent = Math.max(0, toNum(videoProgress?.current))
  const videoDuration = Math.max(0, toNum(videoProgress?.duration))
  const videoPercent = videoDuration > 0 ? Math.min(100, Math.max(0, (videoCurrent / videoDuration) * 100)) : 0
  const coursePercent = toNum(progress.total) > 0 ? Math.min(100, Math.max(0, (toNum(progress.completed) / Math.max(toNum(progress.total), 1)) * 100)) : 0
  const chapterPercent = toNum(progress.total_chapters) > 0 ? Math.min(100, Math.max(0, (toNum(progress.completed_chapters) / Math.max(toNum(progress.total_chapters), 1)) * 100)) : 0


  return (
    <section className={CARD}>


      <div className="mb-4 flex flex-wrap gap-2">


        <button


          type="button"


          onClick={() => {


            void startTask()


          }}


          disabled={loading || isRunning}


          className="min-h-[44px] cursor-pointer rounded-xl bg-primary px-6 py-3 text-white disabled:cursor-not-allowed disabled:bg-text-muted"


        >


          {loading ? '启动中...' : '开始刷课'}


        </button>


        <button


          type="button"


          onClick={() => {


            void controlTask('pause')


          }}


          disabled={statusText !== 'running'}


          className="min-h-[44px] cursor-pointer rounded-xl border border-amber-300 px-4 py-2 disabled:cursor-not-allowed disabled:border-border"


        >


          暂停


        </button>


        <button


          type="button"


          onClick={() => {


            void controlTask('resume')


          }}


          disabled={statusText !== 'paused'}


          className="min-h-[44px] cursor-pointer rounded-xl border border-success px-4 py-2 disabled:cursor-not-allowed disabled:border-border"


        >


          继续


        </button>


        <button


          type="button"


          onClick={() => {
            if (window.confirm('确定要停止当前刷课任务吗？')) {
              void controlTask('stop')
            }
          }}


          disabled={!taskId || statusText === 'cancelling' || DONE_STATUSES.has(statusText)}


          className="min-h-[44px] cursor-pointer rounded-xl border border-danger/30 px-4 py-2 disabled:cursor-not-allowed disabled:border-border"


        >


          停止


        </button>


      </div>


      <div className="grid gap-3 text-sm md:grid-cols-4">


        <div className="rounded-xl border border-border bg-surface p-3">


          <p className="text-text-muted">任务状态</p>


          <p className="font-semibold">{taskStatus?.status || 'idle'}</p>


        </div>


        <div className="rounded-xl border border-border bg-surface p-3">


          <p className="text-text-muted">当前任务</p>


          <p className="font-semibold">{taskStatus?.current_task || '--'}</p>


        </div>


        <div className="rounded-xl border border-border bg-surface p-3">


          <p className="text-text-muted">课程进度</p>


          <p className="font-semibold">


            {toNum(progress.completed)}/{toNum(progress.total)}（失败 {toNum(progress.failed)}）


          </p>


        </div>


        <div className="rounded-xl border border-border bg-surface p-3">


          <p className="text-text-muted">章节进度</p>


          <p className="font-semibold">


            {toNum(progress.completed_chapters)}/{toNum(progress.total_chapters)}


          </p>


        </div>


      </div>


      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4">
          <p className="text-sm text-text-muted">当前课程</p>
          <p className="mt-1 font-semibold text-text">{currentCourseName || '--'}</p>
          <p className="mt-3 text-sm text-text-muted">当前视频</p>
          <p className="mt-1 font-semibold text-text">{videoProgress?.name || '--'}</p>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-hover">
            <div className="h-full rounded-full bg-primary transition-all duration-200" style={{ width: `${videoPercent}%` }} />
          </div>
          <p className="mt-2 text-xs text-text/70">播放进度：{videoCurrent.toFixed(1)} / {videoDuration.toFixed(1)} 秒（{Math.round(videoPercent)}%）</p>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <p className="text-sm text-text-muted">任务推进</p>
          <p className="mt-1 text-sm text-text/80">课程：{toNum(progress.completed)}/{toNum(progress.total)}（{Math.round(coursePercent)}%）</p>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-hover">
            <div className="h-full rounded-full bg-success transition-all duration-200" style={{ width: `${coursePercent}%` }} />
          </div>
          <p className="mt-3 text-sm text-text/80">章节：{toNum(progress.completed_chapters)}/{toNum(progress.total_chapters)}（{Math.round(chapterPercent)}%）</p>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-hover">
            <div className="h-full rounded-full bg-violet-500 transition-all duration-200" style={{ width: `${chapterPercent}%` }} />
          </div>
        </div>
      </div>
    </section>
  )


}
