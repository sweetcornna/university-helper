import { GLASS_CARD_CLASS } from '../utils'

export default function StatsCards({ todayStats }) {
  const rate = todayStats.total > 0 ? Math.round((todayStats.success / todayStats.total) * 100) : 0
  const stats = [
    { label: '今日成功', value: todayStats.success, tone: 'text-success' },
    { label: '今日失败', value: todayStats.failed, tone: 'text-danger' },
    { label: '成功率', value: `${rate}%`, tone: 'text-text' },
  ]

  return (
    <dl className={`${GLASS_CARD_CLASS} grid grid-cols-3 gap-4`}>
      {stats.map((stat) => (
        <div key={stat.label} className="min-w-0">
          <dt className="text-sm text-text-muted">{stat.label}</dt>
          <dd className={`mt-1 text-2xl font-bold ${stat.tone}`}>{stat.value}</dd>
        </div>
      ))}
    </dl>
  )
}
