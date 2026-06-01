import { act } from 'react-dom/test-utils'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, test } from 'vitest'

import TasksTab from './TasksTab'

const noop = () => {}

const renderTab = (root, tasks) =>
  act(() => {
    root.render(
      <TasksTab
        signinTasks={tasks}
        fetchSigninTasks={noop}
        openBackgroundTask={noop}
        executeSignin={noop}
        executeClassSignin={noop}
      />
    )
  })

describe('TasksTab remote submit link', () => {
  let container
  let root

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  // F60: the Chaoxing-derived submit URL is bound to <a href>; a javascript: URL
  // would execute on click. It must be sanitized to http(s) only.
  test('does not render a javascript: submit URL as a link', () => {
    renderTab(root, [
      {
        courseId: '1',
        type: 'normal',
        remoteEndpoints: { endpoints: { submitSign: { url: 'javascript:alert(document.cookie)' } } },
      },
    ])

    const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href') || '')
    expect(hrefs.some((h) => /javascript:/i.test(h))).toBe(false)
    expect(container.textContent).not.toContain('学习通远程提交接口')
  })

  test('renders a valid https submit URL as a link', () => {
    renderTab(root, [
      {
        courseId: '1',
        type: 'normal',
        remoteEndpoints: { endpoints: { submitSign: { url: 'https://mobilelearn.chaoxing.com/submit' } } },
      },
    ])

    const link = Array.from(container.querySelectorAll('a')).find((a) =>
      /学习通远程提交接口/.test(a.textContent || '')
    )
    expect(link).toBeTruthy()
    expect(link.getAttribute('href')).toBe('https://mobilelearn.chaoxing.com/submit')
  })
})
