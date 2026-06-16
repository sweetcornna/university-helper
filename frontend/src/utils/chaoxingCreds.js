// Shared recall of the last-used Chaoxing account, so the signin and fanya
// pages don't each make the user retype it. Only the username is persisted —
// the password is left to the browser's password manager (autoComplete).
const LAST_USERNAME_KEY = 'cx:lastUsername'

// localStorage can throw (Safari private mode, blocked storage) — guard so a
// failure here never breaks the page.
export function readLastUsername() {
  try {
    return localStorage.getItem(LAST_USERNAME_KEY) || ''
  } catch {
    return ''
  }
}

export function saveLastUsername(username) {
  try {
    if (username) localStorage.setItem(LAST_USERNAME_KEY, username)
  } catch {
    /* ignore */
  }
}
