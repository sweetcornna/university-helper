import { CARD, toNum } from '../utils'


export default function ConfigSection({
  speed, setSpeed,
  concurrency, setConcurrency,
  unopenedStrategy, setUnopenedStrategy,
  tikuProvider, setTikuProvider,
  tikuToken, setTikuToken,
  coverageThreshold, setCoverageThreshold,
  correctOptions, setCorrectOptions,
  wrongOptions, setWrongOptions,
  submitMode, setSubmitMode,
  notifyService, setNotifyService,
  notifyUrl, setNotifyUrl,
}) {


  return (
    <section className={`${CARD} grid gap-4 md:grid-cols-2`}>


      <div className="space-y-3">


        <label className="text-sm text-slate-700">播放速度：{speed.toFixed(1)}x</label>


        <input


          type="range"


          min="1"


          max="2"


          step="0.1"


          value={speed}


          onChange={(event) => setSpeed(toNum(event.target.value, 1.5))}


          className="w-full"


        />


        <label className="text-sm text-slate-700">并发章节：{concurrency}</label>


        <input


          type="range"


          min="1"


          max="16"


          step="1"


          value={concurrency}


          onChange={(event) => setConcurrency(toNum(event.target.value, 4))}


          className="w-full"


        />


        <label className="text-sm text-slate-700">未开放章节策略</label>
        <div className="flex flex-wrap gap-2">
          {[
            { value: 'retry', label: '重试' },
            { value: 'continue', label: '跳过' },
            { value: 'ask', label: '手动处理' },
          ].map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setUnopenedStrategy(opt.value)}
              className={`rounded-full border px-4 py-2 text-sm font-medium transition-all duration-200 cursor-pointer ${
                unopenedStrategy === opt.value
                  ? 'border-transparent bg-slate-900 text-white shadow-md'
                  : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>


      </div>


      <div className="space-y-3">


        <label className="text-sm text-slate-700">题库来源</label>
        <div className="flex flex-wrap gap-2">
          {[
            { value: 'TikuYanxi', label: 'TikuYanxi' },
            { value: 'TikuLike', label: 'TikuLike' },
            { value: 'TikuAdapter', label: 'TikuAdapter' },
            { value: 'AI', label: 'AI' },
            { value: 'SiliconFlow', label: 'SiliconFlow' },
            { value: 'LocalCache', label: 'LocalCache' },
          ].map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setTikuProvider(opt.value)}
              className={`rounded-full border px-4 py-2 text-sm font-medium transition-all duration-200 cursor-pointer ${
                tikuProvider === opt.value
                  ? 'border-transparent bg-slate-900 text-white shadow-md'
                  : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>


        <input


          className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3"


          placeholder="题库 Token（可选）"


          value={tikuToken}


          onChange={(event) => setTikuToken(event.target.value)}


        />


        <label className="text-sm text-slate-700">题库覆盖阈值：{coverageThreshold.toFixed(2)}</label>


        <input


          type="range"


          min="0.5"


          max="1"


          step="0.05"


          value={coverageThreshold}


          onChange={(event) => setCoverageThreshold(toNum(event.target.value, 0.9))}


          className="w-full"


        />


        <input


          className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3"


          placeholder="正确映射，例如：对,正确,是"


          value={correctOptions}


          onChange={(event) => setCorrectOptions(event.target.value)}


        />


        <input


          className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3"


          placeholder="错误映射，例如：错,错误,否"


          value={wrongOptions}


          onChange={(event) => setWrongOptions(event.target.value)}


        />


        <label className="text-sm text-slate-700">提交模式</label>
        <div className="flex flex-wrap gap-2">
          {[
            { value: 'submit', label: '自动提交' },
            { value: 'save', label: '仅保存' },
          ].map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setSubmitMode(opt.value)}
              className={`rounded-full border px-4 py-2 text-sm font-medium transition-all duration-200 cursor-pointer ${
                submitMode === opt.value
                  ? 'border-transparent bg-slate-900 text-white shadow-md'
                  : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>


        <input


          className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3"


          placeholder="通知服务（可选）"


          value={notifyService}


          onChange={(event) => setNotifyService(event.target.value)}


        />


        <input


          className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3"


          placeholder="通知地址（可选）"


          value={notifyUrl}


          onChange={(event) => setNotifyUrl(event.target.value)}


        />


      </div>


    </section>
  )


}
