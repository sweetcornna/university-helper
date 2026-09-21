import { useCallback, useEffect, useState } from 'react'
import { api } from '../../../utils/api'


const ENDPOINT = '/course/chaoxing/preferences'


// The server never returns a stored secret in plaintext — it answers with this
// mask plus a has_* flag. So the mask means "the server already holds one",
// never "the user typed ***": it must be stripped from anything we post.
export const SECRET_MASK = '***'


export const isMaskedSecret = (value) => String(value ?? '').trim() === SECRET_MASK


// Use for any outbound field: a masked value becomes empty rather than leaking
// the sentinel into /course/start's tiku_config.
export const plainSecret = (value) => (isMaskedSecret(value) ? '' : String(value ?? '').trim())


// True when the server said it holds this secret — either via the documented
// has_<field> boolean or by masking the field itself.
const secretStored = (preferences, field) =>
  Boolean(preferences?.[`has_${field}`]) || isMaskedSecret(preferences?.[field])


// Display names for the answer-source codes, for the preflight summary only.
// ConfigSection keeps its own richer list (with hints and the 推荐 badge).
const PROVIDER_LABELS = {
  TikuYanxi: '言溪题库',
  TikuGo: 'GO 题库',
  TikuLike: 'Like 题库',
  TikuAdapter: '题库适配器',
  AI: 'AI 智能答题',
  SiliconFlow: '硅基流动',
  LocalCache: '本地缓存',
}


const asProviderList = (value) => {
  if (Array.isArray(value)) return value.map(String).filter(Boolean)
  const single = String(value ?? '').trim()
  return single ? single.split(',').map((item) => item.trim()).filter(Boolean) : []
}


// One line for the preflight summary: which answer bank the run will use.
export const describeAnswerBank = (preferences, hasAnswerBank) => {
  if (!hasAnswerBank) return '未配置'
  const providers = asProviderList(preferences?.tiku_provider)
  const model = String(preferences?.ai_model || '').trim()
  if (providers.length === 0) return model ? `AI 智能答题（${model}）` : '已保存的题库配置'
  const names = providers.map((item) => PROVIDER_LABELS[item] || item).join(' → ')
  return model && providers.includes('AI') ? `${names}（模型 ${model}）` : names
}


// Copies stored preferences into the page's task-config state. Secrets stay
// masked in state so the "已保存" affordance can render without the plaintext
// ever reaching the browser.
export const applyPreferences = (config, preferences) => {
  if (!config || !preferences) return

  const setText = (setter, value) => {
    const text = String(value ?? '').trim()
    if (text) setter(text)
  }
  const setNumber = (setter, value) => {
    const num = Number(value)
    if (Number.isFinite(num)) setter(num)
  }

  setNumber(config.setSpeed, preferences.speed)
  setNumber(config.setConcurrency, preferences.concurrency)
  setNumber(config.setCoverageThreshold, preferences.coverage_threshold)
  setText(config.setUnopenedStrategy, preferences.unopened_strategy)
  setText(config.setSubmitMode, preferences.submit_mode)
  setText(config.setCorrectOptions, preferences.correct_options)
  setText(config.setWrongOptions, preferences.wrong_options)
  setText(config.setAiEndpoint, preferences.ai_endpoint)
  setText(config.setAiModel, preferences.ai_model)
  setText(config.setNotifyService, preferences.notify_service)
  setText(config.setNotifyUrl, preferences.notify_url)

  const providers = asProviderList(preferences.tiku_provider)
  if (providers.length > 0) config.setTikuProvider(providers)

  if (secretStored(preferences, 'tiku_token')) config.setTikuToken(SECRET_MASK)
  if (secretStored(preferences, 'ai_key')) config.setAiKey(SECRET_MASK)
}


// Body for PUT /preferences. A secret still holding the mask is OMITTED, which
// the backend reads as "leave the stored one alone"; a secret the user actually
// edited is sent verbatim, and an empty string clears it.
const buildSavePayload = (config) => {
  const payload = {
    speed: config.speed,
    concurrency: config.concurrency,
    unopened_strategy: config.unopenedStrategy,
    tiku_provider: Array.isArray(config.tikuProvider)
      ? config.tikuProvider.filter(Boolean)
      : [config.tikuProvider].filter(Boolean),
    ai_endpoint: String(config.aiEndpoint ?? '').trim(),
    ai_model: String(config.aiModel ?? '').trim(),
    coverage_threshold: config.coverageThreshold,
    correct_options: config.correctOptions,
    wrong_options: config.wrongOptions,
    submit_mode: config.submitMode,
    notify_service: String(config.notifyService ?? '').trim(),
    notify_url: String(config.notifyUrl ?? '').trim(),
  }
  if (!isMaskedSecret(config.tikuToken)) payload.tiku_token = String(config.tikuToken ?? '').trim()
  if (!isMaskedSecret(config.aiKey)) payload.ai_key = String(config.aiKey ?? '').trim()
  return payload
}


export default function useTaskPreferences() {

  const [preferences, setPreferences] = useState(null)
  const [hasAnswerBank, setHasAnswerBank] = useState(false)
  // '' once the endpoint has answered. Anything else means we could NOT read
  // the stored settings, which the preflight must say out loud rather than
  // reporting "未配置" as if it were a fact.
  const [loadError, setLoadError] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveResult, setSaveResult] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await api(ENDPOINT)
      // The backend serves the SPA's index.html for any unmatched GET, so a
      // missing route arrives as a 200 with an unrecognisable body — the shape
      // check, not the status code, is what tells us the route exists.
      const known =
        resp && typeof resp === 'object' && ('preferences' in resp || 'has_answer_bank' in resp)
      if (!known) throw new Error('当前后端不支持读取已保存的设置。')
      const stored = resp.preferences && typeof resp.preferences === 'object' ? resp.preferences : null
      setPreferences(stored)
      setHasAnswerBank(Boolean(resp.has_answer_bank))
      setLoadError('')
    } catch (err) {
      setPreferences(null)
      setHasAnswerBank(false)
      setLoadError(err?.message || '读取已保存的设置失败。')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const savePreferences = useCallback(
    async (config) => {
      setSaving(true)
      setSaveResult(null)
      try {
        await api(ENDPOINT, { method: 'PUT', body: JSON.stringify(buildSavePayload(config)) })
        setSaveResult({ ok: true, message: '设置已保存，下次「一键全自动」会直接使用。' })
        await load()
        return true
      } catch (err) {
        setSaveResult({ ok: false, message: err?.message || '保存设置失败，请稍后重试。' })
        return false
      } finally {
        setSaving(false)
      }
    },
    [load]
  )

  return {
    preferences,
    hasAnswerBank,
    loadError,
    loading,
    reload: load,
    saving,
    saveResult,
    savePreferences,
    tikuTokenStored: secretStored(preferences, 'tiku_token'),
    aiKeyStored: secretStored(preferences, 'ai_key'),
  }

}
