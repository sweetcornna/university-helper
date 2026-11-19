export default function StatsCards({ todayStats }) {
  const rate = todayStats.total > 0 ? Math.round((todayStats.success / todayStats.total) * 100) : 0
  const stats = [
    { label: '今日成功', value: todayStats.success, tone: 'text-success' },
    { label: '今日失败', value: todayStats.failed, tone: 'text-danger' },
    { label: '成功率', value: todayStats.total > 0 ? `${rate}%` : '--', tone: 'text-text' },
  ]

  return (
    <dl className="ui-card grid grid-cols-3 divide-x divide-border-subtle">
      {stats.map((stat) => (
        <div key={stat.label} className="min-w-0 px-4 py-3">
          <dt className="catalog-label">{stat.label}</dt>
          <dd className={`font-code mt-1 text-xl font-semibold ${stat.tone}`}>{stat.value}</dd>
        </div>
      ))}
    </dl>
  )
}
