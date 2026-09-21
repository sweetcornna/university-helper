import { clsx } from 'clsx'

const PADDING = {
  none: '',
  compact: 'p-4 sm:p-5',
  normal: 'p-5 sm:p-6',
  spacious: 'p-6 sm:p-8',
}

const TONES = {
  default: 'clay-card',
  subtle: 'rounded-2xl border border-border/70 bg-surface/70',
  elevated: 'clay-card shadow-[0_18px_45px_-28px_rgba(23,32,51,0.55)]',
}

export default function Card({
  children,
  className,
  padding = 'normal',
  tone = 'default',
  as: Component = 'div',
  ...props
}) {
  return (
    <Component
      className={clsx(TONES[tone] || TONES.default, PADDING[padding] || PADDING.normal, className)}
      {...props}
    >
      {children}
    </Component>
  )
}
