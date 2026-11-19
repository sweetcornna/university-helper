import { RefreshCw } from 'lucide-react'

import { Button, EmptyState, StatusBadge } from '../../../components'

import { GLASS_CARD_CLASS } from '../utils'

const formatTime = (value) => {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '--' : date.toLocaleString()
}

export default function HistoryTab({ signinHistory, fetchSigninHistory }) {
  return (
    <section className={`${GLASS_CARD_CLASS} space-y-3`} aria-labelledby="cx-signin-history-heading">
      <div className="flex items-center justify-between gap-3">
        <h2 id="cx-signin-history-heading" className="font-display text-base font-bold text-text">签到历史</h2>
        <Button
          type="button"
          variant="secondary"
          size="icon"
          aria-label="刷新签到历史"
          title="刷新签到历史"
          onClick={fetchSigninHistory}
        >
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>
      {signinHistory.length === 0 ? (
        <EmptyState title="暂无签到历史" />
      ) : (
        <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle bg-surface">
          {signinHistory.map((record, idx) => (
            <li key={idx} className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-1 px-3 py-2.5 sm:grid-cols-[auto_minmax(0,1fr)_auto]">
              <StatusBadge status={record.status === 'success' ? 'success' : record.status || 'unknown'} label={record.status === 'success' ? '成功' : record.status === 'failed' ? '失败' : undefined} />
              <div className="min-w-0">
                <h3 className="break-words text-sm font-semibold text-text">{record.courseName}</h3>
                <p className="mt-0.5 break-words text-sm text-text-muted">{record.message}</p>
              </div>
              <p className="font-code col-start-2 text-xs text-text-muted sm:col-start-auto sm:text-right">{formatTime(record.timestamp)}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
