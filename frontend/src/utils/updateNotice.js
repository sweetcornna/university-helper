// Remembers what an administrator chose in the server update notice. Storage can
// be unavailable (private mode, blocked site data); every access is guarded and
// the notice simply shows again in that case.

export const SKIPPED_VERSION_KEY = 'uh.updateNotice.skippedVersion'
export const SNOOZE_UNTIL_KEY = 'uh.updateNotice.snoozeUntil'
export const SNOOZE_MS = 24 * 60 * 60 * 1000

const read = (key) => {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

const write = (key, value) => {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // ignore: the choice just is not remembered
  }
}

export const shouldShowUpdateNotice = (status, now = Date.now()) => {
  if (!status?.has_update || !status.latest) return false
  if (read(SKIPPED_VERSION_KEY) === status.latest) return false
  const snoozeUntil = Number(read(SNOOZE_UNTIL_KEY))
  return !(Number.isFinite(snoozeUntil) && snoozeUntil > now)
}

export const snoozeUpdateNotice = (now = Date.now()) => write(SNOOZE_UNTIL_KEY, String(now + SNOOZE_MS))

export const skipUpdateVersion = (version) => write(SKIPPED_VERSION_KEY, String(version))
