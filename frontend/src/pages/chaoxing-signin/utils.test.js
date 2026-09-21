import { describe, expect, test } from 'vitest'

import {
  MAX_PHOTO_BYTES,
  fileToBase64,
  validatePhotoFile,
} from './utils'

describe('Chaoxing photo validation', () => {
  test('accepts supported photos at the size limit', () => {
    const file = new File([new Uint8Array(MAX_PHOTO_BYTES)], 'signin.jpg', {
      type: 'image/jpeg',
    })

    expect(() => validatePhotoFile(file)).not.toThrow()
  })

  test('rejects oversized photos before reading them', async () => {
    const file = new File([new Uint8Array(MAX_PHOTO_BYTES + 1)], 'signin.png', {
      type: 'image/png',
    })

    expect(() => validatePhotoFile(file)).toThrow('照片不能超过 5 MB')
    expect(() => fileToBase64(file)).toThrow('照片不能超过 5 MB')
  })

  test('rejects unsupported image types', () => {
    const file = new File(['<svg/>'], 'signin.svg', { type: 'image/svg+xml' })
    expect(() => validatePhotoFile(file)).toThrow('照片仅支持 JPG、PNG 或 WebP')
  })
})
