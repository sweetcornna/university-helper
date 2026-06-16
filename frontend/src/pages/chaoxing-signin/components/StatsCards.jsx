import { AlertCircle, CheckCircle2, TrendingUp } from 'lucide-react'

import { GLASS_CARD_CLASS } from '../utils'

export default function StatsCards({ todayStats }) {
  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
      <div className={GLASS_CARD_CLASS}>
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-8 w-8 text-success" />
          <div>
            <p className="text-sm text-text/70">今日成功</p>
            <p className="text-2xl font-bold text-text">{todayStats.success}</p>
          </div>
        </div>
      </div>
      <div className={GLASS_CARD_CLASS}>
        <div className="flex items-center gap-3">
          <AlertCircle className="h-8 w-8 text-danger" />
          <div>
            <p className="text-sm text-text/70">今日失败</p>
            <p className="text-2xl font-bold text-text">{todayStats.failed}</p>
          </div>
        </div>
      </div>
      <div className={GLASS_CARD_CLASS}>
        <div className="flex items-center gap-3">
          <TrendingUp className="h-8 w-8 text-blue-600" />
          <div>
            <p className="text-sm text-text/70">成功率</p>
            <p className="text-2xl font-bold text-text">
              {todayStats.total > 0 ? Math.round((todayStats.success / todayStats.total) * 100) : 0}%
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
