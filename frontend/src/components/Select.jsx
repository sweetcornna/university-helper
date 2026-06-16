import { useId } from 'react'
import { ChevronDown } from 'lucide-react'
import { clsx } from 'clsx'

/*
 * Token-based <select> wrapper. Replaces the hand-rolled `bg-white/60` native
 * selects that were copy-pasted with ~10 utility classes each and broke in
 * dark mode.
 *
 * options: Array<{ value: string, label: string }>
 */
export default function Select({ label, id, options = [], className, children, ...props }) {
  const generatedId = useId()
  const selectId = id || generatedId

  return (
    <div>
      {label && (
        <label htmlFor={selectId} className="mb-2 block text-sm font-medium text-text">
          {label}
        </label>
      )}
      <div className="relative">
        <select
          id={selectId}
          className={clsx(
            'w-full min-h-[44px] cursor-pointer appearance-none rounded-xl border border-border/60 bg-surface/80 px-4 py-2 pr-10 text-text backdrop-blur-sm transition-all duration-200 hover:border-primary/50 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20',
            className
          )}
          {...props}
        >
          {children || options.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <ChevronDown
          className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
          aria-hidden="true"
        />
      </div>
    </div>
  )
}
