import { useRef } from 'react'
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
  const optionRefs = useRef([])

  const selectOption = (index) => {
    const option = OPTIONS[index]
    if (!option) return
    setTheme(option.value)
    optionRefs.current[index]?.focus()
  }

  const handleKeyDown = (event, index) => {
    let nextIndex = index
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
      nextIndex = (index + 1) % OPTIONS.length
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      nextIndex = (index - 1 + OPTIONS.length) % OPTIONS.length
    } else if (event.key === 'Home') {
      nextIndex = 0
    } else if (event.key === 'End') {
      nextIndex = OPTIONS.length - 1
    } else {
      return
    }
    event.preventDefault()
    selectOption(nextIndex)
  }

  return (
    <div
      role="radiogroup"
      aria-label="主题"
      className={`inline-flex items-center gap-0.5 rounded-full border border-border/60 bg-surface/70 p-0.5 backdrop-blur-sm ${className}`}
    >
      {OPTIONS.map(({ value, label, Icon }, index) => {
        const active = theme === value
        return (
          <button
            key={value}
            ref={(element) => {
              optionRefs.current[index] = element
            }}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={label}
            title={label}
            tabIndex={active ? 0 : -1}
            onClick={() => setTheme(value)}
            onKeyDown={(event) => handleKeyDown(event, index)}
            className={`flex h-11 w-11 items-center justify-center rounded-full transition-colors sm:h-8 sm:w-8 ${
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
