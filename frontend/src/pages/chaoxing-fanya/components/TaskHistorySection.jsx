import { CARD, formatTaskTime, labelTaskHistory, taskStatusLabel } from '../utils'


export default function TaskHistorySection({ taskHistory, taskId, selectTaskFromHistory }) {

  // Sorted newest-first and labelled 任务一, 任务二, … — a raw task_id is an
  // opaque hex string and a column of them is unreadable.
  const rows = labelTaskHistory(taskHistory)


  return (
    <section className={CARD}>


      <h2 className="mb-4 text-xl font-semibold text-text">选择任务以恢复</h2>


      {rows.length === 0 ? (


        <p className="text-sm text-text-muted">暂无历史任务</p>


      ) : (


        <div className="space-y-2">


          {rows.map((task) => {


            const selected = task.task_id === taskId


            return (


              <button


                key={task.task_id}


                type="button"


                aria-label={`恢复任务 ${task.task_id}`}


                aria-pressed={selected}


                onClick={() => {


                  void selectTaskFromHistory(task.task_id)


                }}


                className={`min-h-[44px] w-full cursor-pointer rounded-xl border px-4 py-3 text-left transition-colors duration-200 ${


                  selected


                    ? 'border-primary bg-primary/10'


                    : 'border-border bg-surface hover:border-primary/40 hover:bg-surface-hover'


                }`}


              >


                <p className="text-sm font-semibold text-text" title={task.task_id}>
                  {task.label}
                </p>


                <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-text/70">


                  <span title={task.status || 'unknown'}>
                    状态：{taskStatusLabel(task.status)}
                  </span>


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
