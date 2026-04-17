import { Clock } from 'lucide-react'

import {
  MAX_CHECK_INTERVAL_MINUTES,
  GLASS_PANEL_CLASS,
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
}) {
  return (
    <div className="mt-6 space-y-6">
      <div>
        <h3 className="text-lg font-bold text-text mb-4">自动签到设置</h3>
        <div className="space-y-4">
          <div className={`${GLASS_PANEL_CLASS} flex items-center justify-between`}>
            <div>
              <p className="font-medium text-text">自动签到</p>
              <p className="text-sm text-text/70">按设定周期自动检查并签到</p>
            </div>
            <button
              onClick={() => setAutoSignin(!autoSignin)}
              className={`relative inline-flex h-11 w-20 min-h-[44px] min-w-[44px] items-center rounded-full px-1 transition-colors duration-200 cursor-pointer ${
                autoSignin ? 'bg-primary' : 'bg-gray-300'
              }`}
            >
              <span
                className={`inline-block h-8 w-8 transform rounded-full bg-white transition-transform duration-200 ${
                  autoSignin ? 'translate-x-10' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          <div className={GLASS_PANEL_CLASS}>
            <label className="block text-sm font-medium text-text mb-2">
              检查间隔（分钟）
            </label>
            <input
              type="number"
              min="1"
              max={String(MAX_CHECK_INTERVAL_MINUTES)}
              value={checkInterval}
              onChange={(e) => setCheckInterval(clampCheckInterval(e.target.value))}
              className="w-full min-h-[44px] rounded-xl border border-white/30 bg-white/60 px-4 py-2 text-text backdrop-blur-sm transition-all duration-200 hover:border-primary/50 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>

          <div className={GLASS_PANEL_CLASS}>
            <label className="block text-sm font-medium text-text mb-2">
              自动签到类型
            </label>
            <select
              value={autoSignFilter}
              onChange={(e) => setAutoSignFilter(e.target.value)}
              className="w-full min-h-[44px] rounded-xl border border-white/30 bg-white/60 px-4 py-2 text-text backdrop-blur-sm transition-all duration-200 hover:border-primary/50 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 cursor-pointer"
            >
              <option value="all">全部类型</option>
              <option value="normal">普通签到</option>
              <option value="photo">拍照签到</option>
              <option value="location">位置签到</option>
              <option value="qrcode">二维码签到</option>
              <option value="gesture">手势签到（兼容普通）</option>
              <option value="code">签到码签到（兼容普通）</option>
            </select>
            <p className="mt-2 text-xs text-text/70">
              设置会自动保存，开启后每次检查将自动尝试签到，重复任务会短时间去重。
            </p>
          </div>

          {autoSignin && nextCheckCountdown > 0 && (
            <div className="rounded-xl border border-primary/30 bg-primary/10 p-4 backdrop-blur-sm transition-all duration-200">
              <p className="text-sm text-text flex items-center gap-2">
                <Clock className="h-4 w-4" />
                下次检查：{formatCountdown(nextCheckCountdown)}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
