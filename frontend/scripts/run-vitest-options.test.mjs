import { describe, expect, it } from 'vitest'

import {
  createVitestInvocation,
  NO_WEBSTORAGE_FLAG,
  supportsNoWebstorage,
} from './run-vitest-options.mjs'

const BASE_INVOCATION = {
  execPath: '/usr/bin/node',
  vitestEntry: '/workspace/frontend/node_modules/vitest/vitest.mjs',
  vitestArgs: ['--run', 'src/example.test.jsx'],
  cwd: '/workspace/frontend',
}

describe('run-vitest launcher options', () => {
  it('probes the Node CLI flag without producing output', () => {
    const calls = []
    const spawn = (...args) => {
      calls.push(args)
      return { error: undefined, status: 0 }
    }

    expect(supportsNoWebstorage('/usr/bin/node', spawn)).toBe(true)
    expect(calls).toEqual([['/usr/bin/node', [NO_WEBSTORAGE_FLAG, '-e', ''], { stdio: 'ignore' }]])
    expect(supportsNoWebstorage('/usr/bin/node', () => ({ error: undefined, status: 9 }))).toBe(
      false
    )
  })

  it('adds the flag as a Node CLI argument only when supported', () => {
    const supported = createVitestInvocation({
      ...BASE_INVOCATION,
      env: { NODE_OPTIONS: '--trace-warnings' },
      useNoWebstorage: true,
    })
    const unsupported = createVitestInvocation({
      ...BASE_INVOCATION,
      env: { NODE_OPTIONS: '--trace-warnings' },
      useNoWebstorage: false,
    })

    expect(supported.args).toEqual([
      NO_WEBSTORAGE_FLAG,
      BASE_INVOCATION.vitestEntry,
      ...BASE_INVOCATION.vitestArgs,
    ])
    expect(unsupported.args).toEqual([BASE_INVOCATION.vitestEntry, ...BASE_INVOCATION.vitestArgs])
  })

  it('passes the caller environment through without changing NODE_OPTIONS', () => {
    const env = { NODE_OPTIONS: '--trace-warnings' }
    const invocation = createVitestInvocation({
      ...BASE_INVOCATION,
      env,
      useNoWebstorage: true,
    })

    expect(invocation.options.env).toBe(env)
    expect(invocation.options.env.NODE_OPTIONS).toBe('--trace-warnings')
  })
})
