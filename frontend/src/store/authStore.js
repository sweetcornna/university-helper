import { create } from 'zustand'
import {
  getToken,
  getShuakeToken,
  setToken as persistToken,
  setShuakeToken as persistShuakeToken,
  removeToken as persistRemoveToken,
} from '../utils/auth'

/**
 * Thin Zustand wrapper around utils/auth localStorage/sessionStorage helpers.
 *
 * utils/auth remains the authoritative persistence layer; this store hydrates
 * from it on creation and writes through it on every mutation so the two
 * cannot silently diverge. Components that need reactive auth state should
 * read from this store; direct callers of utils/auth continue to work.
 */
export const useAuthStore = create((set) => ({
  token: getToken(),
  shuakeToken: getShuakeToken(),
  user: null,

  setAuth: ({ token, shuakeToken, user } = {}) => {
    if (token !== undefined) {
      // persistToken also writes shuakeToken when provided as 2nd arg
      persistToken(token, shuakeToken)
    } else if (shuakeToken !== undefined) {
      persistShuakeToken(shuakeToken)
    }
    set((state) => ({
      token: token !== undefined ? token : state.token,
      shuakeToken:
        shuakeToken !== undefined
          ? shuakeToken
          : token !== undefined
            ? getShuakeToken()
            : state.shuakeToken,
      user: user !== undefined ? user : state.user,
    }))
  },

  clearAuth: () => {
    persistRemoveToken()
    set({ token: null, shuakeToken: null, user: null })
  },
}))
