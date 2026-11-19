import { Camera, MapPin, QrCode, KeyRound, Hand, CheckSquare, RefreshCw, Clock, AlertTriangle, ExternalLink, HelpCircle } from 'lucide-react'

import { Button, StatusBadge } from '../../../components'
import {
  SIGN_TYPE_META,
  getSignTypeLabel,
  getMissingFieldsForSignType,
  formatMissingFieldLabels,
  pickPrimaryActiveTask,
} from '../utils'
import { pickGuidedActiveTask, signinPlatformUrl } from '../taskPresentation'

const ICON_BY_TYPE = {
  photo: Camera,
  location: MapPin,
  qrcode: QrCode,
  gesture: Hand,
  code: KeyRound,
  normal: CheckSquare,
}

const TypeIcon = ({ type, className }) => {
  const Icon = ICON_BY_TYPE[type] || HelpCircle
  return <Icon className={className} aria-hidden="true" />
}

const formatDeadline = (value) => {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
}

function RefreshButton({ onRefresh, refreshing, compact = false }) {
  return (
    <Button type="button" variant="secondary" size="sm" onClick={onRefresh} disabled={refreshing}>
      <RefreshCw className={`h-4 w-4 ${refreshing ? 'motion-safe:animate-spin' : ''}`} aria-hidden="true" />
      {refreshing ? (compact ? '检测中' : '检测中...') : '重新检测'}
    </Button>
  )
}

function ActivityHeading({ task, label }) {
  const type = String(task?.type || 'normal')
  const courseName = task?.courseName || ''
  const className = task?.className || ''
  const deadline = formatDeadline(task?.deadline)
  const subtitle = [courseName, className && className !== courseName ? className : ''].filter(Boolean).join(' / ')
  return (
    <div className="flex min-w-0 flex-1 items-start gap-3">
      <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-md bg-[rgb(var(--spine-signin))] text-on-spine">
        <TypeIcon type={type} className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-text">{label}</span>
          <span className="inline-flex items-center gap-1 rounded-md border border-border bg-surface px-2 py-0.5 text-xs font-semibold text-text">
            {getSignTypeLabel(type)}
          </span>
        </div>
        <p className="mt-1 truncate text-sm font-semibold text-text">
          {task?.name || '签到活动'}
        </p>
        {subtitle && (
          <p className="mt-0.5 truncate text-xs text-text-muted">{subtitle}</p>
        )}
        {deadline && (
          <p className="mt-1 flex items-center gap-1 text-xs text-text-muted">
            <Clock className="h-3 w-3" aria-hidden="true" />
            截止：{deadline}
          </p>
        )}
      </div>
    </div>
  )
}

export default function AutoSigninBanner({
  signinTasks,
  form,
  submitting,
  onApplyTask,
  onApplyAndSubmit,
  onRefresh,
  refreshing = false,
  error = '',
}) {
  const task = pickPrimaryActiveTask(signinTasks)
  const guided = task ? null : pickGuidedActiveTask(signinTasks)

  if (!task && guided) {
    const platformUrl = signinPlatformUrl(guided)
    const status = String(guided?.status || '').toLowerCase()
    return (
      <div className="ui-index-card spine-signin space-y-3 p-4">
        {error && <p role="alert" className="text-sm text-danger">{error} 下方保留上次检测结果。</p>}
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <ActivityHeading task={guided} label={status === 'active' ? '核验到进行中的签到' : '核验到签到活动'} />
          {status !== 'active' && <StatusBadge status="unknown" label="状态未知" />}
        </div>
        <div className="flex flex-col gap-3 rounded-md border border-warning/35 bg-warning-surface px-3 py-2.5 text-sm text-text sm:flex-row sm:items-center sm:justify-between">
          <p className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
            <span>{guided?.unsupportedReason || '请在学习通完成签到。'}</span>
          </p>
          <div className="flex shrink-0 flex-wrap gap-2">
            {platformUrl && (
              <a href={platformUrl} target="_blank" rel="noreferrer" className="ui-btn-primary ui-btn-sm">
                <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                在学习通打开
              </a>
            )}
            <RefreshButton onRefresh={onRefresh} refreshing={refreshing} compact />
          </div>
        </div>
      </div>
    )
  }

  if (!task) {
    return (
      <div className={`flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3 ${error ? 'border-danger/35 bg-danger-surface' : 'border-dashed border-border bg-surface'}`}>
        <div className="min-w-0">
          <p role={error ? 'alert' : 'status'} className={`text-sm font-semibold ${error ? 'text-danger' : 'text-text'}`}>{refreshing ? '正在检测进行中的签到...' : error ? '签到检测未完成' : '未检测到进行中的签到'}</p>
          {error && <p className="mt-1 text-sm text-text-muted">{error}</p>}
        </div>
        <RefreshButton onRefresh={onRefresh} refreshing={refreshing} />
      </div>
    )
  }

  const type = String(task?.type || 'normal')
  const meta = SIGN_TYPE_META[type] || SIGN_TYPE_META.normal
  const missingFields = getMissingFieldsForSignType(type, form)
  const hasMissing = missingFields.length > 0

  return (
    <div className="ui-index-card spine-signin p-4">
      {error && <p role="alert" className="mb-3 text-sm text-danger">{error} 下方保留上次检测结果。</p>}
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0 flex-1">
          <ActivityHeading task={task} label="检测到当前签到" />
          <div
            className={`mt-3 rounded-md border px-3 py-2 text-sm ${
              hasMissing
                ? 'border-warning/35 bg-warning-surface text-text'
                : 'border-success/35 bg-success-surface text-success'
            }`}
          >
            {hasMissing ? (
              <p className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
                <span>
                  还需填写：<strong>{formatMissingFieldLabels(missingFields)}</strong>
                  <span className="ml-1 text-text-muted">— {meta.hint}</span>
                </span>
              </p>
            ) : (
              <p>已就绪：{meta.hint || '可直接签到。'}</p>
            )}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2 md:w-36 md:flex-col">
          <Button
            type="button"
            variant="secondary"
            onClick={() => onApplyTask?.(task)}
          >
            应用到表单
          </Button>
          <Button
            type="button"
            onClick={() => onApplyAndSubmit?.(task)}
            disabled={submitting || hasMissing}
            title={hasMissing ? `请先填写：${formatMissingFieldLabels(missingFields)}` : undefined}
          >
            {submitting ? '签到中...' : '立即签到'}
          </Button>
          <RefreshButton onRefresh={onRefresh} refreshing={refreshing} compact />
        </div>
      </div>
    </div>
  )
}
