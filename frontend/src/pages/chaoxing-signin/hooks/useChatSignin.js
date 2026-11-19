import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { normalizeChatActivities, parseChatActivityLink, resolveChatSigninTarget } from '../chatSignin'
import { pickMessage } from '../utils'

const SUPPORTED_TYPES = new Set(['normal', 'location'])
const LOCATION_REQUIRED = '这是位置签到，请先设置签到位置（地图选点或使用当前位置）后再提交。'
const UNSUPPORTED_TYPE = '群聊目前支持普通签到和位置签到，请在学习通中完成此活动。'
const NOT_ACTIONABLE = '此活动需在学习通完成签到。'

const activityKey = (chatId, activeId) => `${String(chatId || '').trim()}:${String(activeId || '').trim()}`

// An activity is submittable here only when its type is supported and the
// server has not marked it actionable:false.
const isSubmittable = (activity) => activity?.actionable !== false && SUPPORTED_TYPES.has(activity?.type)

const blockReasonFor = (activity) =>
  String(activity?.unsupportedReason || '').trim() ||
  (SUPPORTED_TYPES.has(activity?.type) ? NOT_ACTIONABLE : UNSUPPORTED_TYPE)

// Known non-actionable activities are keyed by group + activity id. An entry
// with no group id (the server did not say which group) blocks that activity
// id in any group.
const lookupBlocked = (blocked, chatId, activeId) => {
  if (!String(activeId || '').trim()) return ''
  return blocked[activityKey(chatId, activeId)] || blocked[activityKey('', activeId)] || ''
}

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
  // `chatId:activeId` → reason for activities known to be non-actionable here.
  // Kept across re-detection, link parsing and ID edits until the account is
  // re-verified, so the same activity cannot be submitted by another route.
  const [blockedActivities, setBlockedActivities] = useState({})
  const detectionGenerationRef = useRef(0)
  const submitInFlightRef = useRef(false)

  const markBlocked = useCallback((entries) => {
    const valid = entries.filter(({ activeId }) => String(activeId || '').trim())
    if (valid.length === 0) return
    setBlockedActivities((previous) => {
      const next = { ...previous }
      valid.forEach(({ chatId, activeId, reason }) => {
        next[activityKey(chatId, activeId)] = reason || NOT_ACTIONABLE
      })
      return next
    })
  }, [])

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
      const detectedChatId = form.chatId.trim()
      if (detectedChatId) {
        if (!/^[1-9][0-9]{0,31}$/.test(detectedChatId)) throw new Error('群聊 ID 必须为最多 32 位的正整数。')
        query.set('chat_id', detectedChatId)
      }
      const payload = await requestChaoxingApi(`/chat-activities${query.size ? `?${query}` : ''}`)
      if (!current()) return
      // An activity found while checking one group belongs to that group.
      const detectedActivities = normalizeChatActivities(payload).map((activity) => (
        activity.chatId || !detectedChatId ? activity : { ...activity, chatId: detectedChatId }
      ))
      setActivities(detectedActivities)
      markBlocked(detectedActivities
        .filter((activity) => !isSubmittable(activity))
        .map((activity) => ({ chatId: activity.chatId, activeId: activity.activeId, reason: blockReasonFor(activity) })))
      const discoveryWarnings = payload?.data?.warnings || payload?.warnings
      setWarnings(Array.isArray(discoveryWarnings) ? discoveryWarnings.filter((warning) => typeof warning === 'string') : [])
      setDetected(true)
    } catch (err) {
      if (current()) setError(err.message || '群聊活动检测失败，请重试。')
    } finally {
      if (current()) setLoading(false)
    }
  }, [accountGenerationRef, form.chatId, markBlocked, requestChaoxingApi])

  const selectActivity = useCallback((activity) => {
    setForm((previous) => ({ ...previous, activityLink: '', activeId: activity.activeId, chatId: activity.chatId || previous.chatId }))
    setError('')
    const blocked = !isSubmittable(activity)
      ? blockReasonFor(activity)
      : lookupBlocked(blockedActivities, activity.chatId, activity.activeId)
    setNotice(blocked || {
      normal: '已选择普通签到，可提交。',
      location: '已选择位置签到，请先设置签到位置再提交。',
    }[activity.type])
  }, [blockedActivities])

  // The activity the form currently points at, from the typed IDs and/or a
  // pasted official link (a link that is still unparsed counts too).
  const linkTarget = useMemo(() => {
    if (!form.activityLink.trim()) return null
    try {
      return parseChatActivityLink(form.activityLink)
    } catch (_) {
      return null
    }
  }, [form.activityLink])
  const formChatId = form.chatId.trim()
  const formActiveId = form.activeId.trim()
  const currentTarget = {
    chatId: formChatId || linkTarget?.chatId || '',
    activeId: formActiveId || linkTarget?.activeId || '',
  }
  const selectedActivity = activities.find((activity) => activity.activeId === currentTarget.activeId && (!activity.chatId || activity.chatId === currentTarget.chatId))
  const blockedReason =
    lookupBlocked(blockedActivities, currentTarget.chatId, currentTarget.activeId) ||
    (linkTarget ? lookupBlocked(blockedActivities, linkTarget.chatId || formChatId, linkTarget.activeId) : '') ||
    (selectedActivity && !isSubmittable(selectedActivity) ? blockReasonFor(selectedActivity) : '')
  const unsupported = Boolean(blockedReason)
  const needsLocation = !unsupported && (
    selectedActivity?.type === 'location' ||
    locationActivityKey === activityKey(currentTarget.chatId, currentTarget.activeId)
  )

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
    const targetBlocked =
      lookupBlocked(blockedActivities, target.chatId, target.activeId) ||
      (targetActivity && !isSubmittable(targetActivity) ? blockReasonFor(targetActivity) : '')
    if (targetBlocked) {
      setError(targetBlocked)
      return
    }
    const withLocation = hasCoordinates(location)
    const targetKey = activityKey(target.chatId, target.activeId)
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
      const data = err?.payload?.data
      const task = data?.task
      if (task && typeof task === 'object' && task.actionable === false) {
        // The server verified this activity but will not submit it here
        // (e.g. guidance-only, already signed, ended). Never offer the
        // location form or another submit for it.
        const reason = err.message || blockReasonFor(task)
        markBlocked([
          { chatId: target.chatId, activeId: target.activeId, reason },
          {
            chatId: String(task.chatId || task.chat_id || target.chatId),
            activeId: String(task.activeId || task.active_id || target.activeId),
            reason,
          },
        ])
        setLocationActivityKey((previous) => (previous === targetKey ? '' : previous))
      } else if (data?.requiresLocation) {
        setLocationActivityKey(targetKey)
      }
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
    setBlockedActivities({})
    setLocationActivityKey('')
  }, [])

  const isActivityBlocked = useCallback(
    (activity) => !isSubmittable(activity) || Boolean(lookupBlocked(blockedActivities, activity?.chatId, activity?.activeId)),
    [blockedActivities],
  )

  return { form, updateForm, applyLink, activities, warnings, detected, loading, submitting, error, notice, refresh, selectActivity, unsupported, blockedReason, isActivityBlocked, needsLocation, submit, reset }
}
