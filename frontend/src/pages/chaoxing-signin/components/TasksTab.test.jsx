import { act } from 'react'
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
    expect(container.textContent).not.toContain('在学习通提交')
  })

  // The submit endpoint is a write URL; it is never bound to a link, even
  // when it is an https chaoxing.com address.
  test('does not render an https submit endpoint as a link', () => {
    renderTab(root, [
      {
        courseId: '1',
        type: 'normal',
        remoteEndpoints: { endpoints: { submitSign: { url: 'https://mobilelearn.chaoxing.com/pptSign/stuSignajax?activeId=3' } } },
      },
    ])

    expect(container.querySelectorAll('a')).toHaveLength(0)
  })

  test('links only the official confirmation page to open in 学习通', () => {
    const preSign = 'https://mobilelearn.chaoxing.com/newsign/preSign?courseId=1&classId=2&activePrimaryId=3'
    renderTab(root, [
      {
        courseId: '1',
        type: 'normal',
        source: 'live',
        actionable: false,
        remoteEndpoints: {
          endpoints: {
            preSign: { url: preSign },
            submitSign: { url: 'https://mobilelearn.chaoxing.com/pptSign/stuSignajax?activeId=3' },
          },
        },
      },
    ])

    const links = Array.from(container.querySelectorAll('a'))
    expect(links).toHaveLength(1)
    expect(links[0].textContent).toContain('在学习通打开')
    expect(links[0].getAttribute('href')).toBe(preSign)
    expect(container.textContent).not.toContain('填写并签到')
    expect(container.textContent).not.toContain('执行签到')
  })

  test('labels background feed items with the shared task state', () => {
    renderTab(root, [
      { source: 'background', taskId: 'bg-1', status: 'error', message: '最终结果未保存。' },
      { source: 'background', taskId: 'bg-2', status: 'error', message: '签到未获确认，请在学习通核对签到状态。' },
      { source: 'background', taskId: 'bg-3', status: 'mystery' },
    ])

    expect(container.textContent).toContain('最终结果未保存')
    expect(container.textContent).toContain('签到结果未确认')
    expect(container.textContent).toContain('状态未知')
    expect(container.textContent).not.toContain('进行中')
  })
})
