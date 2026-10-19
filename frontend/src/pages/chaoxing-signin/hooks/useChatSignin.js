import { useCallback, useEffect, useRef, useState } from 'react'
import { normalizeChatActivities, parseChatActivityLink, resolveChatSigninTarget } from '../chatSignin'
import { pickMessage } from '../utils'

const SUPPORTED_TYPES = new Set(['normal', 'location'])
const LOCATION_REQUIRED = '这是位置签到，请先设置签到位置（地图选点或使用当前位置）后再提交。'

const hasCoordinates = (location) => {
  const latitude = Number.parseFloat(location?.latitude)
  const longitude = Number.parseFloat(location?.longitude)
  return Number.isFinite(latitude) && Number.isFinite(longitude) && !(latitude === -1 && longitude === -1) && !(latitude === 0 && longitude === 0)
}

export default function useChatSignin({ requestChaoxingApi, username, password, location, accountGenerationRef, onSuccess }) {
  const [form, setForm] = useState({ chatId: '', activeId: '', activityLink: '' })
  const [activities, setActivities] = useState([])
  const [warnings, setWarnings] = useState([])
  const [detected, setDetected] = useState(false)
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  // `chatId:activeId` the platform reported as a location sign-in (manual IDs carry no type).
  const [locationActivityKey, setLocationActivityKey] = useState('')
  const detectionGenerationRef = useRef(0)
  const submitInFlightRef = useRef(false)

  useEffect(() => () => { detectionGenerationRef.current += 1 }, [])

  const updateForm = useCallback((field, value) => {
    detectionGenerationRef.current += 1
    setLoading(false)
    setError('')
    setNotice('')
    setForm((previous) => ({ ...previous, [field]: value }))
    if (field === 'chatId') {
      setActivities([])
      setWarnings([])
      setDetected(false)
    }
  }, [])

  const applyLink = useCallback(() => {
    try {
      const parsed = parseChatActivityLink(form.activityLink)
      detectionGenerationRef.current += 1
      setLoading(false)
      setForm((previous) => ({ ...previous, activeId: parsed.activeId, ...(parsed.chatId ? { chatId: parsed.chatId } : {}) }))
      setActivities([])
      setWarnings([])
      setDetected(false)
      setError('')
      setNotice(parsed.chatId ? '已填入群聊 ID 和活动 ID，请检测活动确认类型。' : '已填入活动 ID；请补充群聊 ID 后检测活动。')
    } catch (err) {
      setError(err.message)
    }
  }, [form.activityLink])

  const refresh = useCallback(async () => {
    const requestGeneration = ++detectionGenerationRef.current
    const accountGeneration = accountGenerationRef.current
    const current = () => requestGeneration === detectionGenerationRef.current && accountGeneration === accountGenerationRef.current
    setLoading(true)
    setError('')
    setNotice('')
    try {
      const query = new URLSearchParams()
      if (form.chatId.trim()) {
        if (!/^[1-9][0-9]{0,31}$/.test(form.chatId.trim())) throw new Error('群聊 ID 必须为最多 32 位的正整数。')
        query.set('chat_id', form.chatId.trim())
      }
      const payload = await requestChaoxingApi(`/chat-activities${query.size ? `?${query}` : ''}`)
      if (!current()) return
      setActivities(normalizeChatActivities(payload))
      const discoveryWarnings = payload?.data?.warnings || payload?.warnings
      setWarnings(Array.isArray(discoveryWarnings) ? discoveryWarnings.filter((warning) => typeof warning === 'string') : [])
      setDetected(true)
    } catch (err) {
      if (current()) setError(err.message || '群聊活动检测失败，请重试。')
    } finally {
      if (current()) setLoading(false)
    }
  }, [accountGenerationRef, form.chatId, requestChaoxingApi])

  const selectActivity = useCallback((activity) => {
    setForm((previous) => ({ ...previous, activityLink: '', activeId: activity.activeId, chatId: activity.chatId || previous.chatId }))
    setError('')
    setNotice({
      normal: '已选择普通签到，可提交。',
      location: '已选择位置签到，请先设置签到位置再提交。',
    }[activity.type] || '群聊目前支持普通签到和位置签到，请在学习通中完成此活动。')
  }, [])

  const selectedActivity = activities.find((activity) => activity.activeId === form.activeId.trim() && (!activity.chatId || activity.chatId === form.chatId.trim()))
  const unsupported = Boolean(selectedActivity && !SUPPORTED_TYPES.has(selectedActivity.type))
  const needsLocation = selectedActivity?.type === 'location' || locationActivityKey === `${form.chatId.trim()}:${form.activeId.trim()}`

  const submit = async (event) => {
    event.preventDefault()
    if (submitInFlightRef.current) return
    setError('')
    setNotice('')
    if (!username.trim() || !password) {
      setError('请先填写学习通账号和密码。')
      return
    }
    let target
    try {
      target = resolveChatSigninTarget(form)
    } catch (err) {
      setError(err.message)
      return
    }
    const targetActivity = activities.find((activity) => activity.activeId === target.activeId && (!activity.chatId || activity.chatId === target.chatId))
    if (targetActivity && !SUPPORTED_TYPES.has(targetActivity.type)) {
      setError('群聊目前支持普通签到和位置签到，请在学习通中完成此活动。')
      return
    }
    const withLocation = hasCoordinates(location)
    const targetKey = `${target.chatId}:${target.activeId}`
    if ((targetActivity?.type === 'location' || locationActivityKey === targetKey) && !withLocation) {
      setError(LOCATION_REQUIRED)
      return
    }
    submitInFlightRef.current = true
    setSubmitting(true)
    const accountGeneration = accountGenerationRef.current
    try {
      const payload = await requestChaoxingApi('/chat-sign', {
        username: username.trim(),
        password,
        chat_id: target.chatId,
        active_id: target.activeId,
        ...(withLocation
          ? {
              latitude: Number.parseFloat(location.latitude),
              longitude: Number.parseFloat(location.longitude),
              address: String(location.address || '').trim() || undefined,
            }
          : {}),
      })
      if (accountGeneration !== accountGenerationRef.current) return
      const message = pickMessage(payload)
      setNotice(!message || message === 'success' ? '群聊签到成功。' : message)
      onSuccess?.()
    } catch (err) {
      if (accountGeneration !== accountGenerationRef.current) return
      if (err?.payload?.data?.requiresLocation) setLocationActivityKey(targetKey)
      setError(err.message || '群聊签到失败，请重试。')
    } finally {
      submitInFlightRef.current = false
      setSubmitting(false)
    }
  }

  const reset = useCallback(() => {
    detectionGenerationRef.current += 1
    setActivities([])
    setWarnings([])
    setDetected(false)
    setLoading(false)
    setError('')
    setNotice('')
  }, [])

  return { form, updateForm, applyLink, activities, warnings, detected, loading, submitting, error, notice, refresh, selectActivity, unsupported, needsLocation, submit, reset }
}
