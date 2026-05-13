 
import { Camera, MapPin, QrCode, KeyRound, Hand, CheckSquare, RefreshCw, Clock, Target, AlertTriangle, Sparkles } from 'lucide-react'

import { Button } from '../../../components'
import {
  GLASS_PANEL_CLASS,
  SIGN_TYPE_META,
  getSignTypeLabel,
  getMissingFieldsForSignType,
  formatMissingFieldLabels,
  pickPrimaryActiveTask,
} from '../utils'

const ICON_BY_TYPE = {
  photo: Camera,
  location: MapPin,
  qrcode: QrCode,
  gesture: Hand,
  code: KeyRound,
  normal: CheckSquare,
}

const TypeIcon = ({ type, className }) => {
  const Icon = ICON_BY_TYPE[type] || CheckSquare
  return <Icon className={className} />
}

export default function AutoSigninBanner({
  signinTasks,
  form,
  submitting,
  onApplyTask,
  onApplyAndSubmit,
  onRefresh,
  refreshing = false,
}) {
  const task = pickPrimaryActiveTask(signinTasks)

  if (!task) {
    return (
      <div className={`${GLASS_PANEL_CLASS} border-dashed`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="mt-1 rounded-full bg-primary/10 p-2">
              <Sparkles className="h-5 w-5 text-primary" />
            </div>
            <div>
              <p className="text-base font-semibold text-text">未检测到进行中的签到</p>
              <p className="mt-1 text-sm text-text/70">
                老师发起签到后，这里会自动显示类型并提示需要补全的字段。
              </p>
            </div>
          </div>
          <Button
            type="button"
            variant="secondary"
            className="min-h-[44px] cursor-pointer transition-all duration-200 hover:scale-105 disabled:opacity-60 disabled:cursor-not-allowed"
            onClick={onRefresh}
            disabled={refreshing}
          >
            <span className="inline-flex items-center gap-2">
              <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
              {refreshing ? '检测中...' : '重新检测'}
            </span>
          </Button>
        </div>
      </div>
    )
  }

  const type = String(task?.type || 'normal')
  const typeLabel = getSignTypeLabel(type)
  const meta = SIGN_TYPE_META[type] || SIGN_TYPE_META.normal
  const missingFields = getMissingFieldsForSignType(type, form)
  const hasMissing = missingFields.length > 0
  const courseName = task?.courseName || ''
  const className = task?.className || ''
  const deadline = task?.deadline ? new Date(task.deadline).toLocaleString() : ''
  const subtitle = [courseName, className && className !== courseName ? className : ''].filter(Boolean).join(' / ')

  return (
    <div className={`${GLASS_PANEL_CLASS} border-primary/40 bg-primary/5`}>
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="flex items-start gap-3 flex-1 min-w-0">
          <div className="mt-1 rounded-full bg-primary/15 p-2">
            <Target className="h-5 w-5 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-base font-semibold text-text">检测到当前签到</span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/15 px-2.5 py-1 text-xs font-medium text-primary">
                <TypeIcon type={type} className="h-3.5 w-3.5" />
                {typeLabel}
              </span>
            </div>
            <p className="mt-1.5 truncate text-sm font-medium text-text">
              {task?.name || '签到活动'}
            </p>
            {subtitle && (
              <p className="mt-0.5 truncate text-xs text-text/70">{subtitle}</p>
            )}
            {deadline && (
              <p className="mt-1 flex items-center gap-1 text-xs text-text/60">
                <Clock className="h-3 w-3" />
                截止：{deadline}
              </p>
            )}
            <div
              className={`mt-3 rounded-lg border px-3 py-2 text-sm ${
                hasMissing
                  ? 'border-amber-300/60 bg-amber-50/80 text-amber-700'
                  : 'border-emerald-300/60 bg-emerald-50/80 text-emerald-700'
              }`}
            >
              {hasMissing ? (
                <p className="flex items-start gap-2">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    还需填写：<strong>{formatMissingFieldLabels(missingFields)}</strong>
                    <span className="ml-1 text-amber-600/80">— {meta.hint}</span>
                  </span>
                </p>
              ) : (
                <p>已就绪：{meta.hint || '可直接签到。'}</p>
              )}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2 md:flex-col">
          <Button
            type="button"
            variant="secondary"
            className="min-h-[44px] cursor-pointer transition-all duration-200 hover:scale-105 disabled:opacity-60 disabled:cursor-not-allowed"
            onClick={() => onApplyTask?.(task)}
          >
            应用到表单
          </Button>
          <Button
            type="button"
            className="min-h-[44px] cursor-pointer transition-all duration-200 hover:scale-105 disabled:opacity-60 disabled:cursor-not-allowed disabled:hover:scale-100"
            onClick={() => onApplyAndSubmit?.(task)}
            disabled={submitting || hasMissing}
            title={hasMissing ? `请先填写：${formatMissingFieldLabels(missingFields)}` : undefined}
          >
            {submitting ? '签到中...' : '立即签到'}
          </Button>
          <Button
            type="button"
            variant="secondary"
            className="min-h-[44px] cursor-pointer transition-all duration-200 hover:scale-105 disabled:opacity-60 disabled:cursor-not-allowed"
            onClick={onRefresh}
            disabled={refreshing}
          >
            <span className="inline-flex items-center gap-2">
              <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
              {refreshing ? '检测中' : '重新检测'}
            </span>
          </Button>
        </div>
      </div>
    </div>
  )
}
