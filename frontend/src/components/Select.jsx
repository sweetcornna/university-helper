import { useId } from 'react'
import { ChevronDown } from 'lucide-react'
import { clsx } from 'clsx'

export default function Select({
  label,
  hint,
  error,
  id,
  options = [],
  className,
  children,
  'aria-describedby': ariaDescribedBy,
  ...props
}) {
  const generatedId = useId()
  const selectId = id || generatedId
  const hintId = hint ? `${selectId}-hint` : undefined
  const errorId = error ? `${selectId}-error` : undefined
  const describedBy = [ariaDescribedBy, errorId, hintId].filter(Boolean).join(' ') || undefined

  return (
    <div>
      {label && (
        <label htmlFor={selectId} className="mb-2 block text-sm font-semibold text-text">
          {label}
        </label>
      )}
      <div className="relative">
        <select
          id={selectId}
          className={clsx(
            'clay-input min-h-[44px] cursor-pointer appearance-none pr-10',
            error && 'border-danger focus:border-danger focus:ring-danger/20',
            className,
          )}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          {...props}
        >
          {children || options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown
          className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
          aria-hidden="true"
        />
      </div>
      {error && <p id={errorId} className="mt-1.5 text-sm text-danger">{error}</p>}
      {hint && <p id={hintId} className="mt-1.5 text-xs leading-5 text-text-muted">{hint}</p>}
    </div>
  )
}
