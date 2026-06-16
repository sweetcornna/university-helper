import { Monitor, Moon, Sun } from 'lucide-react'
import { useTheme } from './themeContext'

const OPTIONS = [
  { value: 'light', label: '浅色', Icon: Sun },
  { value: 'dark', label: '深色', Icon: Moon },
  { value: 'system', label: '跟随系统', Icon: Monitor },
]

// Compact segmented control for light / dark / system.
export default function ThemeToggle({ className = '' }) {
  const { theme, setTheme } = useTheme()

  return (
    <div
      role="radiogroup"
      aria-label="主题"
      className={`inline-flex items-center gap-0.5 rounded-full border border-border/60 bg-surface/70 p-0.5 backdrop-blur-sm ${className}`}
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const active = theme === value
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={label}
            title={label}
            onClick={() => setTheme(value)}
            className={`flex h-8 w-8 items-center justify-center rounded-full transition-colors ${
              active ? 'bg-primary text-white' : 'text-text-muted hover:bg-surface-hover'
            }`}
          >
            <Icon className="h-4 w-4" aria-hidden="true" />
          </button>
        )
      })}
    </div>
  )
}
