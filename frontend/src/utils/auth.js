// SECURITY TRADEOFF (F61): the access/shuake JWTs are kept in window.sessionStorage,
// which is JS-readable. This means any successful XSS in this origin can read the
// bearer token (e.g. `sessionStorage.getItem('auth_token')`) and exfiltrate it.
//
// sessionStorage is a deliberate improvement over localStorage: it is scoped to a
// single tab and cleared when the tab closes, shrinking the token's lifetime and
// blast radius. The fully XSS-resistant alternative — an httpOnly + Secure +
// SameSite cookie that JS cannot read — is NOT implemented here because it requires
// the backend to set/clear the cookie and the API client to stop sending an
// Authorization header (a cross-cutting backend + frontend change, out of scope for
// a frontend-only fix). We therefore accept the residual risk and treat eliminating
// XSS sinks (e.g. the sanitized href helpers in utils/safeUrl.js) as the primary
// mitigation. Do NOT move these tokens to localStorage (longer-lived, larger blast
// radius) or expose them on `window`.
const TOKEN_KEY = 'auth_token'
const SHUAKE_TOKEN_KEY = 'shuake_token'

const readLegacyToken = (key) => {
  const legacyValue = window.localStorage.getItem(key)
  if (!legacyValue) return null
  window.sessionStorage.setItem(key, legacyValue)
  window.localStorage.removeItem(key)
  return legacyValue
}

export const setToken = (token, shuakeToken) => {
  window.sessionStorage.setItem(TOKEN_KEY, token)
  window.localStorage.removeItem(TOKEN_KEY)
  if (shuakeToken || token) {
    window.sessionStorage.setItem(SHUAKE_TOKEN_KEY, shuakeToken || token)
    window.localStorage.removeItem(SHUAKE_TOKEN_KEY)
  }
}

export const getToken = () => {
  return window.sessionStorage.getItem(TOKEN_KEY) || readLegacyToken(TOKEN_KEY)
}

export const getShuakeToken = () => {
  return window.sessionStorage.getItem(SHUAKE_TOKEN_KEY) || readLegacyToken(SHUAKE_TOKEN_KEY)
}

export const setShuakeToken = (token) => {
  if (token) {
    window.sessionStorage.setItem(SHUAKE_TOKEN_KEY, token)
    window.localStorage.removeItem(SHUAKE_TOKEN_KEY)
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
