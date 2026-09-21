import { useId } from 'react'
import { clsx } from 'clsx'

export default function Input({
  label,
  hint,
  error,
  id,
  className,
  containerClassName,
  trailing,
  'aria-describedby': ariaDescribedBy,
  ...props
}) {
  const generatedId = useId()
  const inputId = id || generatedId
  const hintId = hint ? `${inputId}-hint` : undefined
  const errorId = error ? `${inputId}-error` : undefined
  const describedBy = [ariaDescribedBy, errorId, hintId].filter(Boolean).join(' ') || undefined

  return (
    <div className={containerClassName}>
      {label && (
        <label htmlFor={inputId} className="mb-2 block text-sm font-semibold text-text">
          {label}
        </label>
      )}
      <div className="relative">
        <input
          id={inputId}
          className={clsx(
            'clay-input',
            trailing && 'pr-12',
            error && 'border-danger focus:border-danger focus:ring-danger/20',
            className,
          )}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          {...props}
        />
        {trailing && (
          <div className="absolute inset-y-0 right-1 flex items-center">
            {trailing}
          </div>
        )}
      </div>
      {error && (
        <p id={errorId} className="mt-1.5 text-sm text-danger">
          {error}
        </p>
      )}
      {hint && (
        <p id={hintId} className="mt-1.5 text-xs leading-5 text-text-muted">
          {hint}
        </p>
      )}
    </div>
  )
}
