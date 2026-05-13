import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import ErrorBoundary from '../../src/components/ErrorBoundary'

const Boom = () => {
  throw new Error('boom!')
}

describe('ErrorBoundary', () => {
  it('renders children when no error', () => {
    render(<ErrorBoundary><div>safe</div></ErrorBoundary>)
    expect(screen.getByText('safe')).toBeTruthy()
  })

  it('renders fallback UI when a child throws', () => {
    // Suppress React's expected error log noise for this test.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>
    )
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(screen.getByText('boom!')).toBeTruthy()
    spy.mockRestore()
  })
})
