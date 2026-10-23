import { useEffect, useState } from 'react'

import { TIKU_PROVIDERS } from '../configOptions'

// Non-secret settings are kept in this browser so a returning user can start
// straight from the course list. The 题库 Token and notification URL are
// credentials and stay in memory only.
export const TASK_CONFIG_STORAGE_KEY = 'fanya:taskConfig:v1'

// Default chain: 言溪 first (best, if a token is set), then the free GO题库, so
// 答题 still works without a Token. (The shared answer cache is always
// consulted first, so adding 本地缓存 as an extra link would be redundant.)
export const DEFAULT_TASK_CONFIG = Object.freeze({
  speed: 1.5,
  concurrency: 4,
  unopenedStrategy: 'retry',
  tikuProvider: ['TikuYanxi', 'TikuGo'],
  coverageThreshold: 0.9,
  correctOptions: '对,正确,是',
  wrongOptions: '错,错误,否',
  submitMode: 'submit',
  notifyService: '',
})

const KNOWN_PROVIDERS = new Set(TIKU_PROVIDERS.map((option) => option.value))
const inRange = (value, min, max, fallback) => {
  const n = Number(value)
  return Number.isFinite(n) && n >= min && n <= max ? n : fallback
}

export function readStoredTaskConfig() {
  const defaults = { ...DEFAULT_TASK_CONFIG, tikuProvider: [...DEFAULT_TASK_CONFIG.tikuProvider] }
  let stored
  try {
    stored = JSON.parse(localStorage.getItem(TASK_CONFIG_STORAGE_KEY) || 'null')
  } catch {
    return defaults
  }
  if (!stored || typeof stored !== 'object') return defaults
  const text = (value, fallback) => (typeof value === 'string' ? value : fallback)
  const providers = Array.isArray(stored.tikuProvider)
    ? stored.tikuProvider.filter((value) => KNOWN_PROVIDERS.has(value))
    : defaults.tikuProvider
  return {
    speed: inRange(stored.speed, 1, 2, defaults.speed),
    concurrency: Math.round(inRange(stored.concurrency, 1, 16, defaults.concurrency)),
    unopenedStrategy: ['retry', 'continue', 'ask'].includes(stored.unopenedStrategy) ? stored.unopenedStrategy : defaults.unopenedStrategy,
    tikuProvider: providers,
    coverageThreshold: inRange(stored.coverageThreshold, 0.5, 1, defaults.coverageThreshold),
    correctOptions: text(stored.correctOptions, defaults.correctOptions),
    wrongOptions: text(stored.wrongOptions, defaults.wrongOptions),
    submitMode: ['submit', 'save'].includes(stored.submitMode) ? stored.submitMode : defaults.submitMode,
    notifyService: text(stored.notifyService, defaults.notifyService),
  }
}

export default function useTaskConfig() {
  const [initial] = useState(readStoredTaskConfig)

  const [speed, setSpeed] = useState(initial.speed)
  const [concurrency, setConcurrency] = useState(initial.concurrency)
  const [unopenedStrategy, setUnopenedStrategy] = useState(initial.unopenedStrategy)
  // Ordered list of answer-bank providers; sent to the backend as a
  // comma-separated `provider` (单个=单题库，多个=按顺序回退).
  const [tikuProvider, setTikuProvider] = useState(initial.tikuProvider)
  const [tikuToken, setTikuToken] = useState('')
  const [coverageThreshold, setCoverageThreshold] = useState(initial.coverageThreshold)
  const [correctOptions, setCorrectOptions] = useState(initial.correctOptions)
  const [wrongOptions, setWrongOptions] = useState(initial.wrongOptions)
  const [submitMode, setSubmitMode] = useState(initial.submitMode)
  const [notifyService, setNotifyService] = useState(initial.notifyService)
  const [notifyUrl, setNotifyUrl] = useState('')

  useEffect(() => {
    try {
      localStorage.setItem(TASK_CONFIG_STORAGE_KEY, JSON.stringify({
        speed, concurrency, unopenedStrategy, tikuProvider, coverageThreshold,
        correctOptions, wrongOptions, submitMode, notifyService,
      }))
    } catch {
      /* storage blocked: settings just won't persist */
    }
  }, [speed, concurrency, unopenedStrategy, tikuProvider, coverageThreshold, correctOptions, wrongOptions, submitMode, notifyService])

  const resetToDefaults = () => {
    setSpeed(DEFAULT_TASK_CONFIG.speed)
    setConcurrency(DEFAULT_TASK_CONFIG.concurrency)
    setUnopenedStrategy(DEFAULT_TASK_CONFIG.unopenedStrategy)
    setTikuProvider([...DEFAULT_TASK_CONFIG.tikuProvider])
    setCoverageThreshold(DEFAULT_TASK_CONFIG.coverageThreshold)
    setCorrectOptions(DEFAULT_TASK_CONFIG.correctOptions)
    setWrongOptions(DEFAULT_TASK_CONFIG.wrongOptions)
    setSubmitMode(DEFAULT_TASK_CONFIG.submitMode)
  }

  return {
    speed, setSpeed,
    concurrency, setConcurrency,
    unopenedStrategy, setUnopenedStrategy,
    tikuProvider, setTikuProvider,
    tikuToken, setTikuToken,
    coverageThreshold, setCoverageThreshold,
    correctOptions, setCorrectOptions,
    wrongOptions, setWrongOptions,
    submitMode, setSubmitMode,
    notifyService, setNotifyService,
    notifyUrl, setNotifyUrl,
    resetToDefaults,
  }
}
