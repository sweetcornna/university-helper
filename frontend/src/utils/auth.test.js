import { describe, expect, test } from 'vitest'

import {
  getShuakeToken,
  getToken,
  isAuthenticated,
  removeToken,
  setToken,
} from './auth'

describe('auth storage', () => {
  test('stores new tokens in localStorage instead of sessionStorage', () => {
    setToken('access-token', 'shuake-token')

    expect(window.localStorage.getItem('auth_token')).toBe('access-token')
    expect(window.localStorage.getItem('shuake_token')).toBe('shuake-token')
    expect(window.sessionStorage.getItem('auth_token')).toBeNull()
    expect(window.sessionStorage.getItem('shuake_token')).toBeNull()
  })

  test('migrates legacy tokens out of sessionStorage on read', () => {
    window.sessionStorage.setItem('auth_token', 'legacy-access')
    window.sessionStorage.setItem('shuake_token', 'legacy-shuake')

    expect(getToken()).toBe('legacy-access')
    expect(getShuakeToken()).toBe('legacy-shuake')
    expect(window.localStorage.getItem('auth_token')).toBe('legacy-access')
    expect(window.localStorage.getItem('shuake_token')).toBe('legacy-shuake')
    expect(window.sessionStorage.getItem('auth_token')).toBeNull()
    expect(window.sessionStorage.getItem('shuake_token')).toBeNull()
  })

  test('removes tokens from both storages on logout', () => {
    window.localStorage.setItem('auth_token', 'legacy-access')
    window.sessionStorage.setItem('shuake_token', 'active-shuake')

    removeToken()

    expect(window.localStorage.getItem('auth_token')).toBeNull()
    expect(window.localStorage.getItem('shuake_token')).toBeNull()
    expect(window.sessionStorage.getItem('auth_token')).toBeNull()
    expect(window.sessionStorage.getItem('shuake_token')).toBeNull()
    expect(isAuthenticated()).toBe(false)
  })
})
