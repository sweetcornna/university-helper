import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test } from 'vitest'

import ConfigTab from './ConfigTab'

const noop = () => {}
const renderTab = (props) => (
  <ConfigTab
    autoSignin
    setAutoSignin={noop}
    autoSignFilter="all"
    setAutoSignFilter={noop}
    checkInterval={5}
    setCheckInterval={noop}
    nextCheckCountdown={300}
    {...props}
  />
)

afterEach(cleanup)

describe('ConfigTab announcements', () => {
  test('the per-second countdown sits outside every live region', () => {
    const { rerender } = render(renderTab())
    const countdown = screen.getByText('下次检查 5:00')
    expect(countdown.closest('[aria-live], [role="status"], [role="alert"], [role="log"]')).toBe(null)
    expect(screen.getByRole('status')).toHaveTextContent('自动签到运行中')

    rerender(renderTab({ nextCheckCountdown: 299 }))
    expect(screen.getByText('下次检查 4:59')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('自动签到运行中')
  })

  test('announces only state changes', () => {
    const { rerender } = render(renderTab({ paused: true }))
    expect(screen.getByRole('status')).toHaveTextContent('自动签到等待验证账号')
    rerender(renderTab({ autoSignin: false }))
    expect(screen.getByRole('status')).toBeEmptyDOMElement()
    expect(screen.queryByText(/下次检查/)).not.toBeInTheDocument()
  })
})
