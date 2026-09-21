import { dirname, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { createVitestInvocation, supportsNoWebstorage } from './run-vitest-options.mjs'

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const invocation = createVitestInvocation({
  execPath: process.execPath,
  vitestEntry: resolve(frontendRoot, 'node_modules/vitest/vitest.mjs'),
  vitestArgs: process.argv.slice(2),
  cwd: frontendRoot,
  env: process.env,
  useNoWebstorage: supportsNoWebstorage(process.execPath),
})
const result = spawnSync(invocation.command, invocation.args, invocation.options)

if (result.error) throw result.error
process.exit(result.status ?? 1)
