import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import UpdateNotice from './UpdateNotice'
import { api, ApiError } from '../utils/api'
import { isAuthenticated } from '../utils/auth'
import { SKIPPED_VERSION_KEY, SNOOZE_UNTIL_KEY, shouldShowUpdateNotice } from '../utils/updateNotice'

vi.mock('../utils/api', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, api: vi.fn() }
})
vi.mock('../utils/auth', () => ({ isAuthenticated: vi.fn() }))

const STATUS = {
  enabled: true,
  current: '1.4.7',
  latest: '1.4.8',
  has_update: true,
  html_url: 'https://github.com/sweetcornna/university-helper/releases/tag/v1.4.8',
  notes: '- 修复注册问题\n<script>alert(1)</script>',
  commands: {
    bash: 'bash scripts/deploy_server.sh --tag 1.4.8 -y',
    powershell: 'pwsh scripts/deploy_server.ps1 -Tag 1.4.8 -Yes',
  },
}

const clearStorage = () => {
  try {
    window.localStorage.removeItem(SKIPPED_VERSION_KEY)
    window.localStorage.removeItem(SNOOZE_UNTIL_KEY)
  } catch {
    // storage unavailable in this environment
  }
}

describe('UpdateNotice', () => {
  beforeEach(() => {
    clearStorage()
    vi.mocked(api).mockReset()
    vi.mocked(isAuthenticated).mockReturnValue(true)
  })

  afterEach(clearStorage)

  test('stays hidden and makes no request when logged out', () => {
    vi.mocked(isAuthenticated).mockReturnValue(false)
    render(<UpdateNotice />)
    expect(api).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  test('stays hidden for non-admins (403)', async () => {
    vi.mocked(api).mockRejectedValue(new ApiError('Administrator only', { status: 403 }))
    render(<UpdateNotice />)
    await waitFor(() => expect(api).toHaveBeenCalledWith('/system/update'))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  test('shows versions, plain-text notes and both update commands', async () => {
    vi.mocked(api).mockResolvedValue(STATUS)
    render(<UpdateNotice />)

    const dialog = await screen.findByRole('dialog', { name: '学道有新版本' })
    expect(dialog.textContent).toContain('1.4.7')
    expect(dialog.textContent).toContain('1.4.8')
    expect(dialog.textContent).toContain('<script>alert(1)</script>')
    expect(dialog.querySelector('script')).toBeNull()
    expect(screen.getByText(STATUS.commands.bash)).toBeTruthy()
    expect(screen.getByText(STATUS.commands.powershell)).toBeTruthy()
  })

  test('hides when no update is available', async () => {
    vi.mocked(api).mockResolvedValue({ ...STATUS, has_update: false })
    render(<UpdateNotice />)
    await waitFor(() => expect(api).toHaveBeenCalled())
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  test('"跳过这个版本" closes the notice for that version only', async () => {
    vi.mocked(api).mockResolvedValue(STATUS)
    const user = userEvent.setup()
    render(<UpdateNotice />)

    await user.click(await screen.findByRole('button', { name: '跳过这个版本' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  test('"稍后提醒" closes the notice', async () => {
    vi.mocked(api).mockResolvedValue(STATUS)
    const user = userEvent.setup()
    render(<UpdateNotice />)

    await user.click(await screen.findByRole('button', { name: '稍后提醒' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('shouldShowUpdateNotice', () => {
  const storage = new Map()

  beforeEach(() => {
    storage.clear()
    vi.stubGlobal('localStorage', {
      getItem: (key) => (storage.has(key) ? storage.get(key) : null),
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: (key) => storage.delete(key),
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  test('respects a skipped version and an active snooze', () => {
    expect(shouldShowUpdateNotice(STATUS, 1000)).toBe(true)

    storage.set(SKIPPED_VERSION_KEY, '1.4.8')
    expect(shouldShowUpdateNotice(STATUS, 1000)).toBe(false)
    expect(shouldShowUpdateNotice({ ...STATUS, latest: '1.4.9' }, 1000)).toBe(true)

    storage.clear()
    storage.set(SNOOZE_UNTIL_KEY, '5000')
    expect(shouldShowUpdateNotice(STATUS, 1000)).toBe(false)
    expect(shouldShowUpdateNotice(STATUS, 6000)).toBe(true)
  })

  test('still shows when storage throws', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('blocked')
      },
    })
    expect(shouldShowUpdateNotice(STATUS, 1000)).toBe(true)
  })
})
