import { CARD } from '../utils'


export default function LogSection({ logs }) {


  return (
    <section className={CARD}>


      <h2 className="mb-3 text-xl font-semibold text-slate-900">任务日志</h2>


      <div className="max-h-72 space-y-1 overflow-y-auto rounded-xl bg-slate-950 p-4 text-sm">


        {logs.length === 0 ? (


          <p className="text-slate-400">暂无日志</p>


        ) : (


          logs.map((item, index) => (


            <div key={`${item.timestamp}-${index}`} className="text-slate-200">


              [{new Date(item.timestamp).toLocaleTimeString('zh-CN', { hour12: false })}] {item.message}


            </div>


          ))


        )}


      </div>


    </section>
  )


}
