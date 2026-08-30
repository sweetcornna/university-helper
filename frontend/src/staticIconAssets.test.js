import { statSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const frontendRoot = process.cwd()
const publicRoot = join(frontendRoot, 'public')

async function loadIconReferences() {
  const indexHtml = await readFile(join(frontendRoot, 'index.html'), 'utf8')
  const document = new DOMParser().parseFromString(indexHtml, 'text/html')
  const indexIcons = [...document.querySelectorAll('link[href]')]
    .filter((link) =>
      link.rel.split(/\s+/).some((relation) => relation === 'icon' || relation.endsWith('-icon'))
    )
    .map((link) => link.getAttribute('href'))

  const manifest = JSON.parse(await readFile(join(publicRoot, 'site.webmanifest'), 'utf8'))
  const manifestIcons = manifest.icons.map((icon) => icon.src)

  const viteConfig = await readFile(join(frontendRoot, 'vite.config.js'), 'utf8')
  const includeAssetsMatch = viteConfig.match(/includeAssets:\s*\[([\s\S]*?)\]/)
  if (!includeAssetsMatch) {
    throw new Error('vite.config.js must declare VitePWA includeAssets')
  }
  const includeAssets = [...includeAssetsMatch[1].matchAll(/['"]([^'"]+)['"]/g)].map(
    ([, asset]) => `/${asset}`,
  )

  return { indexIcons, manifestIcons, includeAssets }
}

describe('static public asset declarations', () => {
  test('reference non-empty files from the public directory', async () => {
    const { indexIcons, manifestIcons, includeAssets } = await loadIconReferences()
    expect(indexIcons).toContain('/favicon.svg')
    expect(manifestIcons).toContain('/favicon.svg')
    expect(includeAssets).toContain('/favicon.svg')

    for (const reference of [...indexIcons, ...manifestIcons, ...includeAssets]) {
      expect(reference).toMatch(/^\/(?!\/)/)
      const stats = statSync(join(publicRoot, reference.slice(1)))
      expect(stats.isFile(), `${reference} must be a file`).toBe(true)
      expect(stats.size, `${reference} must not be empty`).toBeGreaterThan(0)
    }
  })
})
