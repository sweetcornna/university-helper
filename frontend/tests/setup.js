import '@testing-library/jest-dom/vitest'
import { beforeEach, vi } from 'vitest'

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

if (!window.localStorage || typeof window.localStorage.setItem !== 'function') {
  Object.defineProperty(window, 'localStorage', {
    value: createMemoryStorage(),
    configurable: true,
  })
}

if (!window.sessionStorage || typeof window.sessionStorage.setItem !== 'function') {
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
