export const CHAOXING_REQUEST_TIMEOUT_MS = 20000

export const fetchWithTimeout = async (input, options = {}) => {
  const hasCustomSignal = Boolean(options.signal)
  const controller = hasCustomSignal ? null : new AbortController()
  const timeoutId = !hasCustomSignal
    ? setTimeout(() => controller?.abort(), CHAOXING_REQUEST_TIMEOUT_MS)
    : null

  const requestOptions = {
    ...options,
    ...(hasCustomSignal ? {} : { signal: controller.signal }),
  }

  try {
    return await fetch(input, requestOptions)
  } catch (error) {
    if (error?.name === 'AbortError' && !hasCustomSignal) {
      throw new Error('请求超时，请稍后重试。')
    }
    throw error
  } finally {
    if (timeoutId !== null) {
      clearTimeout(timeoutId)
    }
  }
}
