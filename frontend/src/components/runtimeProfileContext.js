import { createContext, useContext } from 'react'

export const RuntimeProfileContext = createContext(null)

export const useRuntimeProfile = () => {
  const value = useContext(RuntimeProfileContext)
  if (!value) {
    throw new Error('useRuntimeProfile must be used inside RuntimeProfileProvider')
  }
  return value
}
