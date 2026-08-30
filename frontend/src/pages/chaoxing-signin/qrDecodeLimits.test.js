import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import jsQR from 'jsqr'

import {
  ALLOWED_QR_IMAGE_TYPES,
  MAX_QR_FILE_BYTES,
  MAX_QR_IMAGE_DIMENSION,
  MAX_QR_IMAGE_PIXELS,
  decodeQrCodeFromFile,
} from './utils'

vi.mock('jsqr', () => ({ default: vi.fn() }))

const createFile = (overrides = {}) => ({
  type: 'image/png',
  size: 1,
  ...overrides,
})

const installDecodeHarness = ({
  naturalWidth = 64,
  naturalHeight = 64,
  width = naturalWidth,
  height = naturalHeight,
  getImageData = vi.fn(() => ({
    data: new Uint8ClampedArray(width * height * 4),
    width,
    height,
  })),
} = {}) => {
  let readerInstance
  const FileReaderMock = vi.fn(function MockFileReader() {
    readerInstance = this
    this.result = 'data:image/png;base64,AAAA'
    this.readAsDataURL = vi.fn(() => this.onload?.())
  })

  let imageInstance
  const ImageMock = vi.fn(function MockImage() {
    imageInstance = this
    this.naturalWidth = naturalWidth
    this.naturalHeight = naturalHeight
    this.width = width
    this.height = height
    Object.defineProperty(this, 'src', {
      configurable: true,
      set: (value) => {
        this.srcValue = value
        this.onload?.()
      },
    })
  })

  const context = {
    drawImage: vi.fn(),
    getImageData,
  }
  const canvas = {
    width: 0,
    height: 0,
    getContext: vi.fn(() => context),
  }
  const createElement = vi.spyOn(document, 'createElement').mockReturnValue(canvas)

  vi.stubGlobal('FileReader', FileReaderMock)
  vi.stubGlobal('Image', ImageMock)

  return {
    canvas,
    context,
    createElement,
    get image() {
      return imageInstance
    },
    get reader() {
      return readerInstance
    },
  }
}

describe('decodeQrCodeFromFile resource limits', () => {
  beforeEach(() => {
    jsQR.mockReset()
    jsQR.mockReturnValue({ data: 'https://example.test/check-in' })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  test('rejects an oversized file before constructing a FileReader', async () => {
    const FileReaderMock = vi.fn()
    vi.stubGlobal('FileReader', FileReaderMock)

    await expect(
      decodeQrCodeFromFile(createFile({ size: MAX_QR_FILE_BYTES + 1 })),
    ).rejects.toThrow('二维码图片不能超过 5 MB')

    expect(FileReaderMock).not.toHaveBeenCalled()
  })

  test('rejects an unsupported MIME type before constructing a FileReader', async () => {
    const FileReaderMock = vi.fn()
    vi.stubGlobal('FileReader', FileReaderMock)

    await expect(
      decodeQrCodeFromFile(createFile({ type: 'image/svg+xml' })),
    ).rejects.toThrow('二维码图片格式不受支持')

    expect(ALLOWED_QR_IMAGE_TYPES.has('image/svg+xml')).toBe(false)
    expect(FileReaderMock).not.toHaveBeenCalled()
  })

  test('rejects oversized image dimensions before creating a canvas', async () => {
    const harness = installDecodeHarness({
      naturalWidth: MAX_QR_IMAGE_DIMENSION + 1,
      naturalHeight: 64,
      width: 64,
      height: 64,
    })

    await expect(decodeQrCodeFromFile(createFile())).rejects.toThrow('二维码图片尺寸过大')

    expect(harness.createElement).not.toHaveBeenCalled()
    expect(harness.context.getImageData).not.toHaveBeenCalled()
    expect(jsQR).not.toHaveBeenCalled()
  })

  test('rejects images over the total pixel limit before creating a canvas', async () => {
    const width = 4096
    const height = Math.floor(MAX_QR_IMAGE_PIXELS / width) + 1
    const harness = installDecodeHarness({
      naturalWidth: width,
      naturalHeight: height,
    })

    await expect(decodeQrCodeFromFile(createFile())).rejects.toThrow('二维码图片尺寸过大')

    expect(harness.createElement).not.toHaveBeenCalled()
    expect(jsQR).not.toHaveBeenCalled()
  })

  test.each([
    ['canvas creation', (harness) => {
      harness.createElement.mockImplementation(() => {
        throw new Error('canvas unavailable')
      })
    }],
    ['getImageData', (harness) => {
      harness.context.getImageData.mockImplementation(() => {
        throw new Error('readback failed')
      })
    }],
    ['jsQR', () => {
      jsQR.mockImplementation(() => {
        throw new Error('decoder failed')
      })
    }],
  ])('turns a synchronous %s failure into a rejected promise', async (_name, configureFailure) => {
    const harness = installDecodeHarness()
    configureFailure(harness)

    await expect(decodeQrCodeFromFile(createFile())).rejects.toThrow('无法识别二维码')
  })

  test('decodes a small supported image with jsQR', async () => {
    const harness = installDecodeHarness()

    await expect(decodeQrCodeFromFile(createFile())).resolves.toBe('https://example.test/check-in')

    expect(harness.reader.readAsDataURL).toHaveBeenCalledWith(expect.objectContaining({ type: 'image/png' }))
    expect(harness.context.drawImage).toHaveBeenCalledWith(harness.image, 0, 0)
    expect(jsQR).toHaveBeenCalledWith(
      expect.any(Uint8ClampedArray),
      64,
      64,
    )
  })
})
