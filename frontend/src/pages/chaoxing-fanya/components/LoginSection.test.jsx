import { act, cleanup, render, screen } from '@testing-library/react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import LoginSection from './LoginSection'

const noop = () => {}

const baseProps = {
  username: '',
  setUsername: noop,
  password: '',
  setPassword: noop,
  loginLoading: false,
  handleLogin: noop,
  sessionStatus: 'inactive',
  sessionUsername: '',
  sessionExpiresAt: '',
  switchAccount: noop,
  switchLoading: false,
  credentialsRequired: false,
}

const qrResponse = () => ({
  session_id: 's1',
  status: 'pending',
  qr_code: 'BASE64PNG',
})

describe('LoginSection', () => {
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

  const render = (props = {}) =>
    act(() => {
      root.render(<LoginSection {...baseProps} {...props} />)
    })

  const findTab = (label) =>
    Array.from(container.querySelectorAll('[role="tab"]')).find((tab) =>
      tab.textContent?.includes(label)
    )

  test('shows the credential form and no login-method toggle without a QR endpoint', () => {
    render()

    expect(container.querySelector('#fanya-username')).not.toBeNull()
    expect(container.querySelector('#fanya-password')).not.toBeNull()
    expect(findTab('扫码登录')).toBeUndefined()
  })

  test('offers 扫码登录 and swaps in the QR panel', async () => {
    const request = vi.fn(async () => qrResponse())
    render({ qrRequest: request, onQrSuccess: noop })

    expect(findTab('账号密码')).toBeTruthy()

    await act(async () => {
      findTab('扫码登录').click()
    })

    expect(container.querySelector('img[alt="学习通登录二维码"]')).not.toBeNull()
    expect(request).toHaveBeenCalledWith('/qr-login', { method: 'POST' })
  })

  test('hides the form and shows a status line while a session is held', () => {
    render({ sessionStatus: 'active', sessionUsername: 'student01' })

    expect(container.textContent).toContain('已登录学习通账号')
    expect(container.textContent).toContain('student01')
    expect(container.querySelector('#fanya-password')).toBeNull()
  })

  test('shows a placeholder while the session probe is in flight', () => {
    render({ sessionStatus: 'probing' })

    expect(container.textContent).toContain('正在检查学习通登录状态')
    expect(container.querySelector('#fanya-username')).toBeNull()
  })
})

const props = {
  username: 'user-a',
  setUsername: () => {},
  password: 'pass-a',
  setPassword: () => {},
  handleLogin: () => {},
}

describe('LoginSection pending credentials', () => {
  afterEach(() => {
    cleanup()
  })

  test('disables both credential inputs while login is pending', () => {
    const { rerender } = render(<LoginSection {...props} loginLoading={false} />)

    expect(screen.getByRole('textbox', { name: '超星账号' })).toBeEnabled()
    expect(screen.getByLabelText('密码')).toBeEnabled()

    rerender(<LoginSection {...props} loginLoading />)

    expect(screen.getByRole('textbox', { name: '超星账号' })).toBeDisabled()
    expect(screen.getByLabelText('密码')).toBeDisabled()
    expect(screen.getByRole('button', { name: '登录中...' })).toBeDisabled()
  })
})
