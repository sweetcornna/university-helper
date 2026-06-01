import { describe, expect, test } from 'vitest'
import { safeHref } from './safeUrl'

describe('safeHref', () => {
  test('allows absolute http and https URLs unchanged', () => {
    expect(safeHref('https://mobilelearn.chaoxing.com/x')).toBe('https://mobilelearn.chaoxing.com/x')
    expect(safeHref('http://example.com/a?b=c')).toBe('http://example.com/a?b=c')
  })

  test('allows protocol-relative URLs (inherit page http(s) scheme)', () => {
    expect(safeHref('//cdn.chaoxing.com/x')).toBe('//cdn.chaoxing.com/x')
  })

  test('blocks javascript: URLs (the XSS sink) in any casing or with whitespace', () => {
    expect(safeHref('javascript:alert(document.cookie)')).toBe('')
    expect(safeHref('  javascript:alert(1)')).toBe('')
    expect(safeHref('JavaScript:alert(1)')).toBe('')
    expect(safeHref('\tjavascript:alert(1)')).toBe('')
    expect(safeHref('jAvAsCrIpT:\nalert(1)')).toBe('')
  })

  test('blocks data:, vbscript:, mailto: and other non-http(s) schemes', () => {
    expect(safeHref('data:text/html,<script>alert(1)</script>')).toBe('')
    expect(safeHref('vbscript:msgbox(1)')).toBe('')
    expect(safeHref('mailto:a@b.com')).toBe('')
    expect(safeHref('file:///etc/passwd')).toBe('')
  })

  test('blocks relative paths so only absolute external links are emitted', () => {
    expect(safeHref('/relative/path')).toBe('')
    expect(safeHref('relative')).toBe('')
  })

  test('returns empty string for nullish / non-string / blank input', () => {
    expect(safeHref('')).toBe('')
    expect(safeHref('   ')).toBe('')
    expect(safeHref(null)).toBe('')
    expect(safeHref(undefined)).toBe('')
    expect(safeHref(123)).toBe('')
    expect(safeHref({})).toBe('')
  })
})
