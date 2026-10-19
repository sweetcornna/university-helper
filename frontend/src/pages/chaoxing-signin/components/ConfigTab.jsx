import { Clock } from 'lucide-react'

import { Input, Select } from '../../../components'
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
  return (
    <div className={`${GLASS_CARD_CLASS} space-y-4`}>
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-lg font-bold text-text">自动签到</h2>
          <p className="mt-1 text-sm text-text-muted">
            {autoSignin && paused ? '验证账号后开始检查；需保持本页打开。' : '按间隔检测并签到，需保持本页打开。'}
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={autoSignin}
          aria-label="自动签到"
          onClick={() => setAutoSignin(!autoSignin)}
          className={`relative inline-flex h-11 w-20 min-h-[44px] min-w-[44px] shrink-0 cursor-pointer items-center rounded-full px-1 transition-colors duration-200 ${
            autoSignin ? 'bg-primary' : 'bg-border'
          }`}
        >
          <span
            className={`inline-block h-8 w-8 transform rounded-full bg-surface transition-transform duration-200 ${
              autoSignin ? 'translate-x-10' : 'translate-x-1'
            }`}
          />
        </button>
      </div>

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

      {autoSignin && nextCheckCountdown > 0 && (
        <p className="flex items-center gap-2 text-sm text-text-muted">
          <Clock className="h-4 w-4" aria-hidden="true" />
          下次检查：{formatCountdown(nextCheckCountdown)}
        </p>
      )}
    </div>
  )
}
