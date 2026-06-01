import { act } from 'react-dom/test-utils'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

vi.mock('../../../utils/api', () => ({
  api: vi.fn(),
  ApiError: class ApiError extends Error {},
}))

import { api } from '../../../utils/api'
import CoursePortalSection from './CoursePortalSection'

const flush = async () => {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

const COURSE = { courseId: '200', classId: '300', cpi: '400', courseName: '高等数学' }

describe('CoursePortalSection', () => {
  let container
  let root
  let fetchSpy

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    api.mockReset()
    api.mockResolvedValue({
      status: 'success',
      data: { items: [{ id: '1', title: '第一次签到', status: 'active' }], url: 'https://mobilelearn.chaoxing.com/x' },
    })
    // Any direct browser call to chaoxing.com would go through fetch — spy on it.
    fetchSpy = vi.fn(() => Promise.resolve({ ok: true, status: 200, text: async () => '{}' }))
    global.fetch = fetchSpy
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.restoreAllMocks()
  })

  test('fetches the course tab through the backend proxy', async () => {
    await act(async () => {
      root.render(
        <CoursePortalSection courses={[COURSE]} selectedCourses={[]} setError={() => {}} setNotice={() => {}} />
      )
    })
    await flush()

    expect(api).toHaveBeenCalled()
    const endpoint = String(api.mock.calls[0][0])
    expect(endpoint).toContain('/course/chaoxing/course/')
    expect(endpoint).toContain('/tabs/activities')
    expect(endpoint).toContain(encodeURIComponent('200_300_400'))
  })

  test('never issues a direct browser request to chaoxing.com', async () => {
    await act(async () => {
      root.render(
        <CoursePortalSection courses={[COURSE]} selectedCourses={[]} setError={() => {}} setNotice={() => {}} />
      )
    })
    await flush()

    const hitChaoxing = fetchSpy.mock.calls.some(([url]) => String(url).includes('chaoxing.com'))
    expect(hitChaoxing).toBe(false)
  })

  test('renders proxied items returned by the backend', async () => {
    await act(async () => {
      root.render(
        <CoursePortalSection courses={[COURSE]} selectedCourses={[]} setError={() => {}} setNotice={() => {}} />
      )
    })
    await flush()

    expect(container.textContent).toContain('第一次签到')
  })

  // F33: backend/Chaoxing-supplied URLs must be sanitized before binding to href.
  test('strips javascript: URLs from the "open in Chaoxing" link (no XSS sink)', async () => {
    api.mockResolvedValue({
      status: 'success',
      data: {
        items: [{ id: '1', title: '恶意活动' }],
        url: 'javascript:alert(document.cookie)',
      },
    })
    await act(async () => {
      root.render(
        <CoursePortalSection courses={[COURSE]} selectedCourses={[]} setError={() => {}} setNotice={() => {}} />
      )
    })
    await flush()

    const anchors = Array.from(container.querySelectorAll('a'))
    const hrefs = anchors.map((a) => a.getAttribute('href') || '')
    expect(hrefs.some((h) => /javascript:/i.test(h))).toBe(false)
    // The malicious top-level URL must not be rendered as a link at all.
    expect(anchors.some((a) => /在学习通打开/.test(a.textContent || ''))).toBe(false)
  })

  test('strips javascript: URLs from per-item links (no XSS sink)', async () => {
    api.mockResolvedValue({
      status: 'success',
      data: {
        items: [{ id: '1', title: '活动', url: 'javascript:alert(1)' }],
      },
    })
    await act(async () => {
      root.render(
        <CoursePortalSection courses={[COURSE]} selectedCourses={[]} setError={() => {}} setNotice={() => {}} />
      )
    })
    await flush()

    const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href') || '')
    expect(hrefs.some((h) => /javascript:/i.test(h))).toBe(false)
    // The "打开" link should not be rendered for an unsafe URL.
    expect(container.textContent).not.toContain('打开')
  })

  // F67: shell-only tabs carry no top-level url; the link is restored from
  // data.tab.shellUrl computed by the backend.
  test('restores the "open in Chaoxing" link from data.tab.shellUrl for shell tabs', async () => {
    api.mockResolvedValue({
      status: 'success',
      data: {
        items: [],
        message: 'This Chaoxing tab is opened through the course shell URL.',
        tab: { shellUrl: 'https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid=200' },
      },
    })
    await act(async () => {
      root.render(
        <CoursePortalSection courses={[COURSE]} selectedCourses={[]} setError={() => {}} setNotice={() => {}} />
      )
    })
    await flush()

    const link = Array.from(container.querySelectorAll('a')).find((a) =>
      /在学习通打开/.test(a.textContent || '')
    )
    expect(link).toBeTruthy()
    expect(link.getAttribute('href')).toBe(
      'https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid=200'
    )
  })

  // F66: a stale slow response for a previous tab must not overwrite the newer one.
  test('ignores an out-of-order stale response from a previously selected tab', async () => {
    let resolveSlow
    const slow = new Promise((resolve) => {
      resolveSlow = resolve
    })
    // First call (activities, mounted) is slow; second call (chapters) is fast.
    api.mockReset()
    api
      .mockImplementationOnce(() => slow)
      .mockResolvedValue({
        status: 'success',
        data: { items: [{ id: 'c1', title: '第一章' }] },
      })

    await act(async () => {
      root.render(
        <CoursePortalSection courses={[COURSE]} selectedCourses={[]} setError={() => {}} setNotice={() => {}} />
      )
    })
    await flush()

    // Switch to the 章节 (chapters) tab — fires the fast request which resolves first.
    const chaptersBtn = Array.from(container.querySelectorAll('button')).find((b) =>
      /章节/.test(b.textContent || '')
    )
    await act(async () => {
      chaptersBtn.click()
    })
    await flush()
    expect(container.textContent).toContain('第一章')

    // Now the earlier (activities) request finally resolves with different data.
    await act(async () => {
      resolveSlow({
        status: 'success',
        data: { items: [{ id: 'a1', title: '过期活动' }] },
      })
      await slow
    })
    await flush()

    // The stale activities result must NOT have overwritten the chapters body.
    expect(container.textContent).toContain('第一章')
    expect(container.textContent).not.toContain('过期活动')
  })
})
