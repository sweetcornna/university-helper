import { AlertCircle, CheckCircle2, RefreshCw } from 'lucide-react'

import { Button } from '../../../components'

import { GLASS_CARD_CLASS, GLASS_PANEL_CLASS } from '../utils'

export default function HistoryTab({ signinHistory, fetchSigninHistory }) {
  return (
    <div className={`${GLASS_CARD_CLASS} space-y-4`}>
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-bold text-text">签到历史</h2>
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
        <p className="py-6 text-center text-sm text-text-muted">暂无签到历史</p>
      ) : (
        <div className="space-y-3">
          {signinHistory.map((record, idx) => (
            <div key={idx} className={`${GLASS_PANEL_CLASS} flex items-start gap-3`}>
              {record.status === 'success' ? (
                <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" aria-hidden="true" />
              ) : (
                <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-danger" aria-hidden="true" />
              )}
              <div className="min-w-0 flex-1">
                <h3 className="break-words font-medium text-text">{record.courseName}</h3>
                <p className="mt-1 break-words text-sm text-text-muted">{record.message}</p>
                <p className="mt-1 text-xs text-text-muted">{new Date(record.timestamp).toLocaleString()}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
