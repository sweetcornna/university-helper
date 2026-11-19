import { clsx } from 'clsx'

const PADDING = {
  none: '',
  compact: 'p-4',
  normal: 'p-4 sm:p-5',
  spacious: 'p-5 sm:p-7',
}

const TONES = {
  default: 'ui-card',
  index: 'ui-index-card',
  subtle: 'ui-panel',
  elevated: 'ui-index-card',
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
      className={clsx(TONES[tone] || TONES.default, PADDING[padding] ?? PADDING.normal, className)}
      {...props}
    >
      {children}
    </Component>
  )
}
