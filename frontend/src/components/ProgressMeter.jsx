import { clsx } from 'clsx'

const BAR_TONES = {
  primary: 'bg-primary',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  muted: 'bg-text-muted',
}

const clamp = (value) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 0
  return Math.min(100, Math.max(0, parsed))
}

// A ruled progress bar with a written-out value; `known=false` renders an
// explicit "no progress data" track rather than a misleading 0%.
export default function ProgressMeter({ label, value, detail, tone = 'primary', known = true, className }) {
  const percent = clamp(value)
  return (
    <div className={clsx('space-y-1.5', className)}>
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <span className="font-semibold text-text">{label}</span>
        <span className="font-code text-text-muted">{known ? `${Math.round(percent)}%` : '暂无数据'}</span>
      </div>
      <div
        className="relative h-2 overflow-hidden rounded-full bg-sunken"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={known ? Math.round(percent) : undefined}
        aria-valuetext={known ? `${Math.round(percent)}%` : '暂无进度数据'}
      >
        {known && (
          <div
            className={clsx('h-full rounded-full transition-[width] duration-300', BAR_TONES[tone] || BAR_TONES.primary)}
            style={{ width: `${percent}%` }}
          />
        )}
      </div>
      {detail && <p className="text-xs leading-5 text-text-muted">{detail}</p>}
    </div>
  )
}
