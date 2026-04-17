import { CARD, formatTaskTime } from '../utils'


export default function TaskHistorySection({ taskHistory, taskId, selectTaskFromHistory }) {


  return (
    <section className={CARD}>


      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">


        <h2 className="text-xl font-semibold text-slate-900">最近任务 / 历史任务</h2>


        <p className="text-xs text-slate-500">点击任意任务可恢复详情和日志</p>


      </div>


      {taskHistory.length === 0 ? (


        <p className="text-sm text-slate-400">暂无历史任务</p>


      ) : (


        <div className="space-y-2">


          {taskHistory.map((task) => {


            const selected = task.task_id === taskId


            return (


              <button


                key={task.task_id}


                type="button"


                onClick={() => {


                  void selectTaskFromHistory(task.task_id)


                }}


                className={`min-h-[44px] w-full cursor-pointer rounded-xl border px-4 py-3 text-left transition-colors duration-200 ${


                  selected


                    ? 'border-sky-400 bg-sky-50'


                    : 'border-slate-200 bg-white hover:border-sky-200 hover:bg-slate-50'


                }`}


              >


                <p className="font-mono text-sm text-slate-900">{task.task_id}</p>


                <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-slate-600">


                  <span>状态：{task.status || 'unknown'}</span>


                  <span>更新时间：{formatTaskTime(task.updated_at)}</span>


                </div>


              </button>


            )


          })}


        </div>


      )}


    </section>
  )


}
