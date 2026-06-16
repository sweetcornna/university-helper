import { useCallback, useEffect, useMemo, useState } from 'react'
import { ThemeContext } from './themeContext'

const STORAGE_KEY = 'uh:theme'

function readStoredTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  } catch {
    /* ignore */
  }
  return 'system'
}

function darkMediaQuery() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null
  try {
    return window.matchMedia('(prefers-color-scheme: dark)') || null
  } catch {
    return null
  }
}

function systemPrefersDark() {
  return Boolean(darkMediaQuery()?.matches)
}

/*
 * Applies the chosen theme by toggling the `dark` class on <html> (the
 * tailwind darkMode:'class' switch). Previously the .dark token set existed
 * but nothing ever activated it — so dark mode was dead code. Default is
 * 'system' so the OS preference is honoured out of the box.
 */
export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(readStoredTheme)
  const [resolvedTheme, setResolvedTheme] = useState(() =>
    (theme === 'system' ? systemPrefersDark() : theme === 'dark') ? 'dark' : 'light'
  )

  useEffect(() => {
    const apply = () => {
      const isDark = theme === 'dark' || (theme === 'system' && systemPrefersDark())
      document.documentElement.classList.toggle('dark', isDark)
      setResolvedTheme(isDark ? 'dark' : 'light')
    }
    apply()

    if (theme !== 'system') return undefined
    const media = darkMediaQuery()
    if (!media || typeof media.addEventListener !== 'function') return undefined
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [theme])

  const setTheme = useCallback((next) => {
    setThemeState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* ignore */
    }
  }, [])

  const value = useMemo(
    () => ({ theme, resolvedTheme, setTheme }),
    [theme, resolvedTheme, setTheme]
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
