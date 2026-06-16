import { AlertCircle, CheckCircle2, RefreshCw } from 'lucide-react'

import { Button } from '../../../components'

import { GLASS_PANEL_CLASS } from '../utils'

export default function HistoryTab({ signinHistory, fetchSigninHistory }) {
  return (
    <div className="mt-6 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-bold text-text">签到历史</h3>
        <Button
          type="button"
          variant="secondary"
          className="min-h-[44px] min-w-[44px] cursor-pointer transition-all duration-200"
          onClick={fetchSigninHistory}
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>
      {signinHistory.length === 0 ? (
        <p className="text-center text-text/70 py-8">暂无签到历史</p>
      ) : (
        <div className="space-y-3">
          {signinHistory.map((record, idx) => (
            <div
              key={idx}
              className={GLASS_PANEL_CLASS}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3 flex-1">
                  <div className="mt-1">
                    {record.status === 'success' ? (
                      <CheckCircle2 className="h-5 w-5 text-success" />
                    ) : (
                      <AlertCircle className="h-5 w-5 text-danger" />
                    )}
                  </div>
                  <div className="flex-1">
                    <h4 className="font-medium text-text">{record.courseName}</h4>
                    <p className="text-sm text-text/70 mt-1">{record.message}</p>
                    <p className="text-xs text-text/60 mt-1">
                      {new Date(record.timestamp).toLocaleString()}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
