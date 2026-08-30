import { spawnSync } from 'node:child_process'

export const NO_WEBSTORAGE_FLAG = '--no-webstorage'

export function supportsNoWebstorage(execPath, spawn = spawnSync) {
  const result = spawn(execPath, [NO_WEBSTORAGE_FLAG, '-e', ''], { stdio: 'ignore' })
  return result.status === 0 && !result.error
}

export function createVitestInvocation({
  execPath,
  vitestEntry,
  vitestArgs,
  cwd,
  env,
  useNoWebstorage,
}) {
  return {
    command: execPath,
    args: [...(useNoWebstorage ? [NO_WEBSTORAGE_FLAG] : []), vitestEntry, ...vitestArgs],
    options: {
      cwd,
      env,
      stdio: 'inherit',
    },
  }
}
