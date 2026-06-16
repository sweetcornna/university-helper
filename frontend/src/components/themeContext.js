import { createContext, useContext } from 'react'

// theme: 'light' | 'dark' | 'system'
export const ThemeContext = createContext({
  theme: 'system',
  resolvedTheme: 'light',
  setTheme: () => {},
})

export function useTheme() {
  return useContext(ThemeContext)
}
