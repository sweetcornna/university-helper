// Sanitize backend/Chaoxing-supplied URLs before binding them to an <a href>.
//
// Course/tab/sign-in data is proxied from the external Chaoxing platform, whose
// returned URLs are attacker-influenceable and never protocol-validated. React
// does NOT sanitize href protocols, so a `javascript:` / `data:` / `vbscript:`
// href would execute in the user's authenticated session on click (DOM XSS,
// findings F33/F60). Only allow absolute http(s) URLs (and protocol-relative
// `//host` which the browser resolves to the current http(s) scheme); anything
// else collapses to '' so the caller renders no link.

const SAFE_PROTOCOLS = new Set(['http:', 'https:'])

export const safeHref = (value) => {
  if (typeof value !== 'string') return ''
  const trimmed = value.trim()
  if (!trimmed) return ''

  // Protocol-relative URLs (//host/path) inherit the page's http(s) scheme and
  // are safe to keep; resolve against an https base purely to validate them.
  const base = 'https://invalid.example'
  let parsed
  try {
    parsed = new URL(trimmed, base)
  } catch (_) {
    return ''
  }

  if (!SAFE_PROTOCOLS.has(parsed.protocol)) return ''

  // Reject anything that resolved against the placeholder base — i.e. a relative
  // path with no host of its own — so we only ever emit absolute external links.
  if (parsed.hostname === 'invalid.example' && !trimmed.startsWith('//')) return ''

  return trimmed
}
