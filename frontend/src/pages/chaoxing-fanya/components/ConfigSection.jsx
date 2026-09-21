import { useState } from 'react'
import { api } from '../../../utils/api'
import { CARD, toNum } from '../utils'

const UNOPENED_STRATEGIES = [
  { value: 'retry', label: '重试' },
  { value: 'continue', label: '跳过' },
  { value: 'ask', label: '手动处理' },
]

const SUBMIT_MODES = [
  { value: 'submit', label: '自动提交' },
  { value: 'save', label: '仅保存' },
]

const TIKU_PROVIDERS = [
  { value: 'TikuYanxi', label: '言溪题库', hint: '通用题库（需 Token）' },
  { value: 'TikuGo', label: 'GO 题库', hint: '免费搜题源' },
  { value: 'TikuLike', label: 'Like 题库', hint: '备用题库（需 Token）' },
  { value: 'TikuAdapter', label: '题库适配器', hint: '自定义适配' },
  { value: 'AI', label: 'AI 智能答题', hint: '无匹配时由 AI 作答' },
  { value: 'SiliconFlow', label: '硅基流动', hint: 'AI 服务（需 Token）' },
  { value: 'LocalCache', label: '本地缓存', hint: '仅用已缓存答案' },
]

function PillGroup({ label, options, value, onChange }) {
  return (
    <div role="group" aria-label={label}>
      <span className="mb-2 block text-sm font-medium text-text/80">{label}</span>
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => {
          const active = value === opt.value
          return (
            <button
              key={opt.value}
              type="button"
              aria-pressed={active}
              onClick={() => onChange(opt.value)}
              className={`flex flex-col items-start rounded-xl border px-4 py-2 text-sm font-medium transition-all duration-200 cursor-pointer ${
                active
                  ? 'border-transparent bg-primary text-white shadow-md'
                  : 'border-border bg-surface text-text/70 hover:border-border hover:bg-surface-hover'
              }`}
            >
              <span className="flex items-center gap-1.5">
                {opt.label}
              </span>
              {opt.hint && (
                <span className={`text-[11px] ${active ? 'text-white/70' : 'text-text-muted'}`}>
                  {opt.hint}
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}

function MultiPillGroup({ label, options, value, onChange, hint }) {
  const toggle = (optValue) => {
    if (value.includes(optValue)) {
      onChange(value.filter((item) => item !== optValue))
    } else {
      onChange([...value, optValue])
    }
  }
  return (
    <div role="group" aria-label={label}>
      <span className="mb-2 block text-sm font-medium text-text/80">{label}</span>
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => {
          const order = value.indexOf(opt.value)
          const active = order >= 0
          return (
            <button
              key={opt.value}
              type="button"
              aria-pressed={active}
              aria-label={`${opt.label}${active ? `，回退顺序 ${order + 1}` : ''}`}
              onClick={() => toggle(opt.value)}
              className={`flex flex-col items-start rounded-xl border px-4 py-2 text-sm font-medium transition-all duration-200 cursor-pointer ${
                active
                  ? 'border-transparent bg-primary text-white shadow-md'
                  : 'border-border bg-surface text-text/70 hover:border-border hover:bg-surface-hover'
              }`}
            >
              <span className="flex items-center gap-1.5">
                {active && (
                  <span
                    aria-hidden="true"
                    className="inline-grid min-w-5 place-items-center rounded-full border border-current/40 px-1 text-[11px] leading-4"
                  >
                    {order + 1}
                  </span>
                )}
                {opt.label}
              </span>
              {opt.hint && (
                <span className={`text-[11px] ${active ? 'text-white/70' : 'text-text-muted'}`}>
                  {opt.hint}
                </span>
              )}
            </button>
          )
        })}
      </div>
      {hint && <p className="mt-2 text-xs text-text-muted">{hint}</p>}
    </div>
  )
}

export default function ConfigSection({
  speed,
  setSpeed,
  concurrency,
  setConcurrency,
  unopenedStrategy,
  setUnopenedStrategy,
  tikuProvider,
  setTikuProvider,
  tikuToken,
  setTikuToken,
  aiEndpoint,
  setAiEndpoint,
  aiKey,
  setAiKey,
  aiModel,
  setAiModel,
  coverageThreshold,
  setCoverageThreshold,
  correctOptions,
  setCorrectOptions,
  wrongOptions,
  setWrongOptions,
  submitMode,
  setSubmitMode,
  notifyService,
  setNotifyService,
  notifyUrl,
  setNotifyUrl,
}) {
  const [aiProbeLoading, setAiProbeLoading] = useState(false)
  const [aiProbeResult, setAiProbeResult] = useState(null)

  const probeAi = async () => {
    const endpoint = (aiEndpoint || '').trim()
    const key = (aiKey || '').trim()
    const model = (aiModel || '').trim()
    if (!endpoint || !key || !model) {
      setAiProbeResult({ ok: false, message: '请先填写请求地址、密钥和模型名' })
      return
    }
    setAiProbeLoading(true)
    setAiProbeResult(null)
    try {
      const resp = await api('/course/ai/test', {
        method: 'POST',
        body: JSON.stringify({ endpoint, key, model }),
        timeoutMs: 30000,
      })
      const reply = resp?.data?.reply || resp?.reply || ''
      setAiProbeResult({
        ok: true,
        message: `测活成功${reply ? `：模型回复「${reply}」` : ''}`,
      })
    } catch (err) {
      setAiProbeResult({
        ok: false,
        message: err?.message || '测活失败',
      })
    } finally {
      setAiProbeLoading(false)
    }
  }

  return (
    <section className={`${CARD} space-y-6`}>
      {/* Everyday playback settings */}
      <div className="grid gap-5 md:grid-cols-2">
        <div className="space-y-2">
          <label htmlFor="fanya-speed" className="text-sm font-medium text-text/80">
            播放速度：{speed.toFixed(1)}x
          </label>
          <input
            id="fanya-speed"
            type="range"
            min="1"
            max="2"
            step="0.1"
            value={speed}
            onChange={(event) => setSpeed(toNum(event.target.value, 1.5))}
            className="w-full"
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="fanya-concurrency" className="text-sm font-medium text-text/80">
            并发章节：{concurrency}
          </label>
          <input
            id="fanya-concurrency"
            type="range"
            min="1"
            max="16"
            step="1"
            value={concurrency}
            onChange={(event) => setConcurrency(toNum(event.target.value, 4))}
            className="w-full"
          />
          <p className="text-xs text-text-muted">并发越高越快，但过高可能触发风控，建议 3–6。</p>
        </div>

        <PillGroup
          label="未开放章节策略"
          options={UNOPENED_STRATEGIES}
          value={unopenedStrategy}
          onChange={setUnopenedStrategy}
        />

        <PillGroup
          label="答题提交模式"
          options={SUBMIT_MODES}
          value={submitMode}
          onChange={setSubmitMode}
        />
      </div>

      {/* Answer-source & advanced settings — collapsed by default */}
      <details className="rounded-xl border border-border bg-surface-hover/60 p-4">
        <summary className="cursor-pointer text-sm font-medium text-text/80">
          答题与题库设置（高级）
        </summary>

        <div className="mt-4 space-y-4">
          <MultiPillGroup
            label="题库来源（按选择顺序回退）"
            options={TIKU_PROVIDERS}
            value={tikuProvider}
            onChange={setTikuProvider}
            hint="前一个题库未命中时，按选择顺序回退到下一个。"
          />

          <div>
            <label htmlFor="fanya-tiku-token" className="mb-1 block text-sm font-medium text-text/80">
              题库 Token（可选）
            </label>
            <input
              id="fanya-tiku-token"
              className="w-full rounded-xl border border-border bg-surface px-4 py-3"
              placeholder="部分题库 / AI 服务需要填写"
              value={tikuToken}
              onChange={(event) => setTikuToken(event.target.value)}
            />
          </div>

          {/* Always show AI config so it is not hidden by stale PWA caches or
              unexpected provider state. Required only when AI is selected. */}
          <div className="space-y-3 rounded-xl border border-primary/30 bg-primary/5 p-4">
            <p className="text-sm font-medium text-text/80">
              自定义 AI 供应商配置（OpenAI 兼容协议）
            </p>
            <p className="text-xs text-text-muted">
              支持 DeepSeek、通义千问、OpenAI、本地 Ollama 等。勾选「AI 智能答题」时三项必填；未勾选可留空。
            </p>
            <div>
              <label htmlFor="fanya-ai-endpoint" className="mb-1 block text-sm font-medium text-text/80">
                请求地址 (Endpoint)
              </label>
              <input
                id="fanya-ai-endpoint"
                className="w-full rounded-xl border border-border bg-surface px-4 py-3"
                placeholder="https://api.deepseek.com/v1/chat/completions"
                value={aiEndpoint}
                onChange={(event) => setAiEndpoint(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="fanya-ai-key" className="mb-1 block text-sm font-medium text-text/80">
                密钥 (API Key)
              </label>
              <input
                id="fanya-ai-key"
                type="password"
                className="w-full rounded-xl border border-border bg-surface px-4 py-3"
                placeholder="sk-..."
                value={aiKey}
                onChange={(event) => setAiKey(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="fanya-ai-model" className="mb-1 block text-sm font-medium text-text/80">
                模型名 (Model)
              </label>
              <input
                id="fanya-ai-model"
                className="w-full rounded-xl border border-border bg-surface px-4 py-3"
                placeholder="如 deepseek-chat、qwen-plus、gpt-4o-mini"
                value={aiModel}
                onChange={(event) => setAiModel(event.target.value)}
              />
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={probeAi}
                disabled={aiProbeLoading}
                className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {aiProbeLoading ? '测活中…' : '测活 AI'}
              </button>
              {aiProbeResult && (
                <span
                  className={`text-sm ${
                    aiProbeResult.ok ? 'text-success' : 'text-red-500'
                  }`}
                >
                  {aiProbeResult.message}
                </span>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <label htmlFor="fanya-coverage" className="text-sm font-medium text-text/80">
              题库覆盖阈值：{coverageThreshold.toFixed(2)}
            </label>
            <input
              id="fanya-coverage"
              type="range"
              min="0.5"
              max="1"
              step="0.05"
              value={coverageThreshold}
              onChange={(event) => setCoverageThreshold(toNum(event.target.value, 0.9))}
              className="w-full"
            />
            <p className="text-xs text-text-muted">命中率低于此阈值的题目视为题库未覆盖。</p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="fanya-correct" className="mb-1 block text-sm font-medium text-text/80">
                判断题「正确」映射
              </label>
              <input
                id="fanya-correct"
                className="w-full rounded-xl border border-border bg-surface px-4 py-3"
                placeholder="例如：对,正确,是"
                value={correctOptions}
                onChange={(event) => setCorrectOptions(event.target.value)}
              />
            </div>

            <div>
              <label htmlFor="fanya-wrong" className="mb-1 block text-sm font-medium text-text/80">
                判断题「错误」映射
              </label>
              <input
                id="fanya-wrong"
                className="w-full rounded-xl border border-border bg-surface px-4 py-3"
                placeholder="例如：错,错误,否"
                value={wrongOptions}
                onChange={(event) => setWrongOptions(event.target.value)}
              />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="fanya-notify-service" className="mb-1 block text-sm font-medium text-text/80">
                通知服务（可选）
              </label>
              <input
                id="fanya-notify-service"
                className="w-full rounded-xl border border-border bg-surface px-4 py-3"
                placeholder="如 bark / server酱"
                value={notifyService}
                onChange={(event) => setNotifyService(event.target.value)}
              />
            </div>

            <div>
              <label htmlFor="fanya-notify-url" className="mb-1 block text-sm font-medium text-text/80">
                通知地址（可选）
              </label>
              <input
                id="fanya-notify-url"
                className="w-full rounded-xl border border-border bg-surface px-4 py-3"
                placeholder="任务完成后推送到此地址"
                value={notifyUrl}
                onChange={(event) => setNotifyUrl(event.target.value)}
              />
            </div>
          </div>
        </div>
      </details>
    </section>
  )
}
