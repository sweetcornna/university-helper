import { useId } from 'react'
import { clsx } from 'clsx'

export default function Input({
  label,
  id,
  className,
  ...props
}) {
  // Always associate the label with the control. Callers may omit `id`
  // (e.g. the register form historically did), which previously left the
  // <label htmlFor> dangling and broke click-to-focus + screen readers.
  const generatedId = useId()
  const inputId = id || generatedId

  return (
    <div>
      {label && (
        <label htmlFor={inputId} className="block text-sm font-medium mb-2">
          {label}
        </label>
      )}
      <input
        id={inputId}
        className={clsx('clay-input', className)}
        {...props}
      />
    </div>
  )
}
