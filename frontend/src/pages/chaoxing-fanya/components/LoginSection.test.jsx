import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'

import LoginSection from './LoginSection'

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
