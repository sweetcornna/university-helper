import { forwardRef } from 'react'
import { Loader2 } from 'lucide-react'
import { clsx } from 'clsx'

const VARIANTS = {
  primary: 'ui-btn-primary',
  secondary: 'ui-btn-secondary',
  cta: 'ui-btn-cta',
  ghost: 'ui-btn-ghost',
  danger: 'ui-btn-danger',
}

const SIZES = {
  sm: 'ui-btn-sm',
  md: '',
  lg: 'ui-btn-lg',
  icon: 'ui-btn-icon',
}

const Button = forwardRef(function Button({
  children,
  variant = 'primary',
  size = 'md',
  type = 'button',
  className,
  loading = false,
  loadingLabel,
  disabled,
  ...props
}, ref) {
  return (
    <button
      ref={ref}
      type={type}
      className={clsx(VARIANTS[variant] || VARIANTS.primary, SIZES[size] || SIZES.md, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 shrink-0 motion-safe:animate-spin" aria-hidden="true" />}
      {loading && loadingLabel ? loadingLabel : children}
    </button>
  )
})

export default Button
