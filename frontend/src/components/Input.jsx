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
    <div className={clsx('min-w-0', containerClassName)}>
      {label && (
        <label htmlFor={inputId} className="ui-label">
          {label}
        </label>
      )}
      <div className="relative">
        <input
          id={inputId}
          className={clsx(
            'ui-field',
            trailing && 'pr-11',
            error && 'border-danger focus:border-danger focus:ring-danger/25',
            className,
          )}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          {...props}
        />
        {trailing && (
          <div className="absolute inset-y-0 right-0.5 flex items-center">
            {trailing}
          </div>
        )}
      </div>
      {error && (
        <p id={errorId} className="mt-1.5 text-xs font-medium text-danger">
          {error}
        </p>
      )}
      {hint && (
        <p id={hintId} className="ui-hint">
          {hint}
        </p>
      )}
    </div>
  )
}
