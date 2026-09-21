// Self-hosted single-user tradeoff: tokens live in localStorage so that
// reopening a tab / restarting the browser does not force a re-login.
// Combined with the backend's 7-day ACCESS_TOKEN_EXPIRE_MINUTES this keeps the
// platform session sticky across restarts.
//
// Residual XSS risk: any successful XSS in this origin can still read
// `localStorage.getItem('auth_token')` and exfiltrate it. The fully
// XSS-resistant alternative (httpOnly + Secure + SameSite cookie) would
// require a backend cookie flow and is out of scope for this self-use setup.
// Primary mitigation remains eliminating XSS sinks (e.g. the sanitized href
// helpers in utils/safeUrl.js). Do NOT expose these tokens on `window`.
const TOKEN_KEY = 'auth_token'
const SHUAKE_TOKEN_KEY = 'shuake_token'

// Migrate a token left in sessionStorage by an older build into localStorage.
const readLegacyToken = (key) => {
  const legacyValue = window.sessionStorage.getItem(key)
  if (!legacyValue) return null
  window.localStorage.setItem(key, legacyValue)
  window.sessionStorage.removeItem(key)
  return legacyValue
}

export const setToken = (token, shuakeToken) => {
  window.localStorage.setItem(TOKEN_KEY, token)
  window.sessionStorage.removeItem(TOKEN_KEY)
  if (shuakeToken || token) {
    window.localStorage.setItem(SHUAKE_TOKEN_KEY, shuakeToken || token)
    window.sessionStorage.removeItem(SHUAKE_TOKEN_KEY)
  }
}

export const getToken = () => {
  return window.localStorage.getItem(TOKEN_KEY) || readLegacyToken(TOKEN_KEY)
}

export const getShuakeToken = () => {
  return window.localStorage.getItem(SHUAKE_TOKEN_KEY) || readLegacyToken(SHUAKE_TOKEN_KEY)
}

export const setShuakeToken = (token) => {
  if (token) {
    window.localStorage.setItem(SHUAKE_TOKEN_KEY, token)
    window.sessionStorage.removeItem(SHUAKE_TOKEN_KEY)
  }
}

export const removeToken = () => {
  window.localStorage.removeItem(TOKEN_KEY)
  window.localStorage.removeItem(SHUAKE_TOKEN_KEY)
  window.sessionStorage.removeItem(TOKEN_KEY)
  window.sessionStorage.removeItem(SHUAKE_TOKEN_KEY)
}

export const isAuthenticated = () => {
  return !!getToken()
}
