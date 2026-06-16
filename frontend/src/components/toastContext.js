import { createContext, useContext } from 'react'

export const ToastContext = createContext(null)

const NOOP_API = {
  notify: () => {},
  success: () => {},
  error: () => {},
  info: () => {},
  dismiss: () => {},
}

export function useToast() {
  const ctx = useContext(ToastContext)
  // Fail soft — pages rendered without a provider (e.g. unit tests) get
  // no-ops instead of a crash.
  return ctx || NOOP_API
}
