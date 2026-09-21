// Shared between the two Chaoxing pages — 学习通签到 (/chaoxing-signin) and
// 学习通泛雅 (/chaoxing-fanya). Both talk to the same server-held session and
// both offer the same two ways to create one (password / QR), so the constants
// and predicates live here rather than being duplicated per page.

// How often the browser asks whether the QR has been scanned. The upstream
// code stays valid for ~2 minutes; 2s makes the 已扫码 transition feel prompt
// without hammering the passport endpoint.
export const QR_POLL_INTERVAL_MS = 2000

export const QR_STATUS = {
  IDLE: 'idle',
  LOADING: 'loading',
  PENDING: 'pending',
  SCANNED: 'scanned',
  SUCCESS: 'success',
  FAILED: 'failed',
}

export const QR_STATUS_TEXT = {
  [QR_STATUS.IDLE]: '未开始',
  [QR_STATUS.LOADING]: '加载中',
  [QR_STATUS.PENDING]: '等待扫码',
  [QR_STATUS.SCANNED]: '已扫码，请在手机上确认',
  [QR_STATUS.SUCCESS]: '登录成功',
  [QR_STATUS.FAILED]: '登录失败',
}

// `scanned` must keep polling: the phone still has to confirm, and that
// confirmation — not the scan itself — is what authenticates the session.
export function isQrInFlight(status) {
  return status === QR_STATUS.PENDING || status === QR_STATUS.SCANNED
}

// A 401/403 out of a /chaoxing/* endpoint is CHAOXING asking for its own login,
// not our app session expiring — api.js only wipes the app token for app-JWT
// 401s (see APP_JWT_401_PATTERN there, F62). So when one of these reaches us the
// server-held Chaoxing session is gone and the credential form has to come back.
const CHAOXING_SESSION_LOST =
  /(未登录|请先登录|登录已过期|登录状态已失效|登录态已失效|not logged in|please login|session expired)/i

export function isChaoxingSessionLost(err) {
  const status = Number(err?.status)
  if (status === 401 || status === 403) return true
  return CHAOXING_SESSION_LOST.test(String(err?.message || ''))
}

export const SESSION_LOST_MESSAGE = '学习通登录态已失效，请重新输入账号密码登录。'

// The backend only reuses a stored session when the request carries the account
// that session is bound to, so every action must send the session's own
// username — not whatever happens to be in the form.
export function sessionAccountName({ username, sessionUsername }) {
  return String(sessionUsername || username || '').trim()
}
