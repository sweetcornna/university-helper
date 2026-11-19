import { Clock } from 'lucide-react'

import { Input, Select, Toggle } from '../../../components'
import {
  MAX_CHECK_INTERVAL_MINUTES,
  GLASS_CARD_CLASS,
  clampCheckInterval,
} from '../utils'

const formatCountdown = (seconds) => {
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

export default function ConfigTab({
  autoSignin,
  setAutoSignin,
  autoSignFilter,
  setAutoSignFilter,
  checkInterval,
  setCheckInterval,
  nextCheckCountdown,
  paused = false,
}) {
  const stateText = paused
    ? '等待验证账号'
      : nextCheckCountdown > 0
        ? `下次检查 ${formatCountdown(nextCheckCountdown)}`
        : '检查中'
  // Screen readers hear only state changes (on / waiting for the account),
  // never the per-second countdown, which stays readable on demand.
  const announcement = autoSignin ? (paused ? '自动签到等待验证账号' : '自动签到运行中') : ''

  return (
    <section className={`${GLASS_CARD_CLASS} space-y-4`} aria-labelledby="cx-auto-heading">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 id="cx-auto-heading" className="font-display text-base font-bold text-text">自动签到</h2>
          <p className="mt-1 text-sm text-text-muted">需保持本页打开。</p>
        </div>
        <Toggle label="自动签到" checked={autoSignin} onChange={setAutoSignin} />
      </div>

      <p role="status" className="sr-only">{announcement}</p>
      {autoSignin && (
        <p
          className={`inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-xs font-semibold ${
            paused ? 'border-border bg-surface-hover text-text-muted' : 'border-primary/35 bg-primary/10 text-primary'
          }`}
        >
          <Clock className="h-3.5 w-3.5" aria-hidden="true" />
          {stateText}
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Input
          id="cx-auto-check-interval"
          label="检查间隔（分钟）"
          type="number"
          min="1"
          max={String(MAX_CHECK_INTERVAL_MINUTES)}
          value={checkInterval}
          onChange={(e) => setCheckInterval(clampCheckInterval(e.target.value))}
        />

        <Select
          id="cx-auto-sign-type"
          label="自动签到类型"
          value={autoSignFilter}
          onChange={(e) => setAutoSignFilter(e.target.value)}
        >
          <option value="all">全部类型</option>
          <option value="normal">普通签到</option>
          <option value="photo">拍照签到</option>
          <option value="location">位置签到</option>
          <option value="qrcode">二维码签到</option>
          <option value="gesture">手势签到（兼容普通）</option>
          <option value="code">签到码签到（兼容普通）</option>
        </Select>
      </div>
      <p className="ui-hint mt-0">需在学习通完成的活动会跳过。</p>
    </section>
  )
}
