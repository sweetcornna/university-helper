import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, test } from 'vitest'

import { ThemeProvider } from '../components'
import NotFound from './NotFound'

describe('NotFound', () => {
  test('states the page is missing and offers one way home', () => {
    render(
      <ThemeProvider>
        <MemoryRouter
          initialEntries={['/missing/page']}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <NotFound />
        </MemoryRouter>
      </ThemeProvider>
    )

    expect(screen.getByRole('heading', { level: 1, name: '404 页面不存在' })).toBeTruthy()
    expect(screen.getAllByRole('link')).toHaveLength(1)
    expect(screen.getByRole('link', { name: '返回首页' }).getAttribute('href')).toBe('/')
    expect(screen.queryByText('/missing/page')).toBeNull()
    expect(screen.queryByText('未入藏')).toBeNull()
    expect(screen.queryByText('索书号')).toBeNull()
  })
})
