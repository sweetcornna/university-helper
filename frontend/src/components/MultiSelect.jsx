import { useId, useMemo, useState } from 'react'
import { Check, Search } from 'lucide-react'

/*
 * Touch-friendly multi-select. Replaces native <select multiple>, which on
 * mobile requires long-press / ctrl-click and is effectively impossible to
 * operate with a thumb — yet picking courses/classes is a core action here.
 *
 * options: Array<{ id: string, name: string }>
 * selectedIds: string[]
 * onChange: (nextIds: string[]) => void
 */
export default function MultiSelect({
  label,
  options = [],
  selectedIds = [],
  onChange,
  searchable = true,
  emptyHint = '暂无选项',
  headerAction = null,
  maxHeightClass = 'max-h-60',
}) {
  const [query, setQuery] = useState('')
  const searchId = useId()
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter((o) => String(o.name ?? '').toLowerCase().includes(q))
  }, [options, query])

  const toggle = (id) => {
    if (selectedSet.has(id)) onChange(selectedIds.filter((x) => x !== id))
    else onChange([...selectedIds, id])
  }

  const allSelected = options.length > 0 && selectedIds.length === options.length

  return (
    <div role="group" aria-label={label}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="block text-sm font-medium text-text">{label}</span>
        {headerAction}
      </div>

      {searchable && options.length > 6 && (
        <div className="relative mb-2">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
            aria-hidden="true"
          />
          <input
            id={searchId}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索…"
            aria-label={`搜索${label}`}
            className="clay-input pl-9"
          />
        </div>
      )}

      <div
        className={`${maxHeightClass} divide-y divide-border-subtle overflow-y-auto rounded-xl border border-border/60 bg-surface/60 backdrop-blur-sm`}
      >
        {options.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-text-muted">{emptyHint}</p>
        ) : filtered.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-text-muted">未找到匹配项</p>
        ) : (
          filtered.map((option) => {
            const checked = selectedSet.has(option.id)
            return (
              <label
                key={option.id}
                className="flex min-h-[44px] cursor-pointer items-center gap-3 px-4 py-2 text-sm text-text transition-colors hover:bg-surface-hover"
              >
                <span
                  className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors ${
                    checked ? 'border-primary bg-primary text-white' : 'border-border bg-surface'
                  }`}
                >
                  {checked && <Check className="h-3.5 w-3.5" aria-hidden="true" />}
                </span>
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={checked}
                  onChange={() => toggle(option.id)}
                />
                <span className="flex-1 break-words">{option.name}</span>
              </label>
            )
          })
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => onChange(allSelected ? [] : options.map((o) => o.id))}
          disabled={options.length === 0}
          className="min-h-[36px] rounded-lg border border-border/60 px-3 text-xs text-text/80 transition-colors hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          {allSelected ? '清空' : '全选'}
        </button>
        {selectedIds.length > 0 && !allSelected && (
          <button
            type="button"
            onClick={() => onChange([])}
            className="min-h-[36px] rounded-lg border border-border/60 px-3 text-xs text-text/80 transition-colors hover:bg-surface-hover"
          >
            清空
          </button>
        )}
        <p className="text-xs text-text-muted">
          已选 {selectedIds.length} / {options.length}
        </p>
      </div>
    </div>
  )
}
