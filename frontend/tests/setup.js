import '@testing-library/jest-dom/vitest'
import { beforeEach, vi } from 'vitest'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const createMemoryStorage = () => {
  const store = new Map()
  return {
    getItem(key) {
      return store.has(key) ? store.get(key) : null
    },
    setItem(key, value) {
      store.set(key, String(value))
    },
    removeItem(key) {
      store.delete(key)
    },
    clear() {
      store.clear()
    },
  }
}

const hasUsableStorage = (name) => {
  try {
    const storage = window[name]
    const key = '__storage_probe__'
    storage.setItem(key, key)
    storage.removeItem(key)
    return true
  } catch (_) {
    return false
  }
}

if (!hasUsableStorage('localStorage')) {
  Object.defineProperty(window, 'localStorage', {
    value: createMemoryStorage(),
    configurable: true,
  })
}

if (!hasUsableStorage('sessionStorage')) {
  Object.defineProperty(window, 'sessionStorage', {
    value: createMemoryStorage(),
    configurable: true,
  })
}

if (typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    value: vi.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
    configurable: true,
  })
}

if (typeof window.ResizeObserver !== 'function') {
  class ResizeObserver {
    observe() {}

    unobserve() {}

    disconnect() {}
  }

  Object.defineProperty(window, 'ResizeObserver', {
    value: ResizeObserver,
    configurable: true,
  })
}

if (typeof window.scrollTo !== 'function') {
  window.scrollTo = vi.fn()
}

beforeEach(() => {
  for (const storage of [window.localStorage, window.sessionStorage]) {
    if (!storage || typeof storage.removeItem !== 'function') continue
    storage.removeItem('auth_token')
    storage.removeItem('shuake_token')
  }

  vi.restoreAllMocks()
})
