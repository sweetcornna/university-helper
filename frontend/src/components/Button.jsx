import { Loader2 } from 'lucide-react'
import { clsx } from 'clsx'

const VARIANTS = {
  primary: 'clay-button-primary',
  secondary: 'clay-button-secondary',
  cta: 'clay-button-cta',
  ghost: 'clay-button text-text hover:bg-surface-hover',
  danger: 'clay-button bg-danger text-white hover:bg-danger/90',
}

const SIZES = {
  sm: 'min-h-[38px] rounded-lg px-3 py-1.5 text-sm',
  md: '',
  lg: 'min-h-[48px] px-6 py-3',
  icon: 'h-11 w-11 shrink-0 p-0',
}

export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  type = 'button',
  className,
  loading = false,
  loadingLabel,
  disabled,
  ...props
}) {
  return (
    <button
      type={type}
      className={clsx(VARIANTS[variant] || VARIANTS.primary, SIZES[size] || SIZES.md, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden="true" />}
      {loading && loadingLabel ? loadingLabel : children}
    </button>
  )
}
