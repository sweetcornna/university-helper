import { AlertTriangle } from 'lucide-react'

import { CARD, toNum } from '../utils'
import { ENDPOINT_PROVIDERS, SUBMIT_MODES, TIKU_PROVIDERS, UNOPENED_STRATEGIES, providerLabel } from '../configOptions'

const FIELD = 'clay-input'
const LABEL = 'mb-1 block text-sm font-medium text-text'

function PillGroup({ label, options, value, onChange }) {
  return (
    <div role="group" aria-label={label}>
      <span className="mb-2 block text-sm font-medium text-text">{label}</span>
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => {
          const active = value === opt.value
          return (
            <button
              key={opt.value}
              type="button"
              aria-pressed={active}
              onClick={() => onChange(opt.value)}
              className={`flex min-h-[44px] flex-col items-start justify-center rounded-xl border px-4 py-2 text-sm font-medium transition-all duration-200 cursor-pointer ${
                active
                  ? 'border-transparent bg-primary text-white shadow-md'
                  : 'border-border bg-surface text-text hover:border-primary/40 hover:bg-surface-hover'
              }`}
            >
              <span className="flex items-center gap-1.5">
                {opt.label}
              </span>
              {opt.hint && (
                <span className={`text-[11px] ${active ? 'text-white/85' : 'text-text-muted'}`}>
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
      <span className="mb-2 block text-sm font-medium text-text">{label}</span>
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
              className={`flex min-h-[44px] flex-col items-start justify-center rounded-xl border px-4 py-2 text-sm font-medium transition-all duration-200 cursor-pointer ${
                active
                  ? 'border-transparent bg-primary text-white shadow-md'
                  : 'border-border bg-surface text-text hover:border-primary/40 hover:bg-surface-hover'
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
                <span className={`text-[11px] ${active ? 'text-white/85' : 'text-text-muted'}`}>
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
  resetToDefaults,
}) {
  const endpointProviders = (Array.isArray(tikuProvider) ? tikuProvider : [tikuProvider]).filter((value) => ENDPOINT_PROVIDERS.has(value))

  return (
    <section aria-labelledby="fanya-config-title" className={`${CARD} space-y-6`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="fanya-config-title" className="text-lg font-semibold text-text">学习配置</h2>
          <p className="mt-1 text-sm text-text-muted">不改也能直接开始，默认值适合大多数课程。设置会记在这台设备上（题库 Token 和通知地址除外）。</p>
        </div>
        {resetToDefaults && (
          <button type="button" onClick={resetToDefaults} className="clay-button-secondary min-h-[44px] px-4 text-sm">恢复默认</button>
        )}
      </div>

      {endpointProviders.length > 0 && (
        <p role="alert" className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning-surface px-3 py-2.5 text-sm text-text">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
          <span>
            {endpointProviders.map((value) => `「${providerLabel(value)}」`).join('、')}需要一个公网可访问的服务地址，网页里还不能填写，选上后任务会启动失败。请在下方「答题与题库设置」里取消。
          </span>
        </p>
      )}

      {/* Everyday playback settings */}
      <div className="grid gap-5 md:grid-cols-2">
        <div className="space-y-2">
          <label htmlFor="fanya-speed" className="text-sm font-medium text-text">
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
          <label htmlFor="fanya-concurrency" className="text-sm font-medium text-text">
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
      <details className="rounded-xl border border-border bg-surface-hover/60 p-4" open={endpointProviders.length > 0 || undefined}>
        <summary className="flex min-h-[44px] cursor-pointer items-center text-sm font-medium text-text">
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
            <label htmlFor="fanya-tiku-token" className={LABEL}>
              题库 Token（可选）
            </label>
            <input
              id="fanya-tiku-token"
              className={FIELD}
              placeholder="部分题库 / AI 服务需要填写"
              autoComplete="off"
              aria-describedby="fanya-tiku-token-hint"
              value={tikuToken}
              onChange={(event) => setTikuToken(event.target.value)}
            />
            <p id="fanya-tiku-token-hint" className="mt-1.5 text-xs text-text-muted">只在本页使用，刷新页面后需要重新填写。不填时，需要 Token 的题库会被跳过，由其余题库作答。</p>
          </div>

          <div className="space-y-2">
            <label htmlFor="fanya-coverage" className="text-sm font-medium text-text">
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
              <label htmlFor="fanya-correct" className={LABEL}>
                判断题「正确」映射
              </label>
              <input
                id="fanya-correct"
                className={FIELD}
                placeholder="例如：对,正确,是"
                value={correctOptions}
                onChange={(event) => setCorrectOptions(event.target.value)}
              />
            </div>

            <div>
              <label htmlFor="fanya-wrong" className={LABEL}>
                判断题「错误」映射
              </label>
              <input
                id="fanya-wrong"
                className={FIELD}
                placeholder="例如：错,错误,否"
                value={wrongOptions}
                onChange={(event) => setWrongOptions(event.target.value)}
              />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="fanya-notify-service" className={LABEL}>
                通知服务（可选）
              </label>
              <input
                id="fanya-notify-service"
                className={FIELD}
                placeholder="如 bark / server酱"
                value={notifyService}
                onChange={(event) => setNotifyService(event.target.value)}
              />
            </div>

            <div>
              <label htmlFor="fanya-notify-url" className={LABEL}>
                通知地址（可选）
              </label>
              <input
                id="fanya-notify-url"
                className={FIELD}
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
