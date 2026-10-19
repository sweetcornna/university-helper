const isOfficialHost = (hostname) => hostname === 'chaoxing.com' || hostname.endsWith('.chaoxing.com')

// Activity links are parsed locally; never navigate to or fetch a pasted URL.
export const parseChatActivityLink = (value) => {
  let url
  try {
    url = new URL(String(value).trim())
  } catch (_) {
    throw new Error('请输入完整的学习通官方活动链接。')
  }
  if (!['https:', 'http:'].includes(url.protocol) || !isOfficialHost(url.hostname) || url.username || url.password) {
    throw new Error('仅支持 chaoxing.com 及其子域的官方活动链接。')
  }
  const readId = (keys, label) => {
    const values = keys.flatMap((key) => url.searchParams.getAll(key)).map((item) => item.trim())
    if (new Set(values).size > 1) throw new Error(`活动链接包含不一致的${label}。`)
    return values[0] || ''
  }
  const activeId = readId(['activeId', 'active_id', 'activePrimaryId', 'aid'], '活动 ID')
  const chatId = readId(['chatId', 'chat_id', 'chatid'], '群聊 ID')
  if (!activeId) throw new Error('活动链接中缺少活动 ID（activeId 或 aid）。')
  return { activeId, chatId }
}

export const resolveChatSigninTarget = ({ chatId, activeId, activityLink }) => {
  let targetChatId = String(chatId || '').trim()
  let targetActiveId = String(activeId || '').trim()
  if (String(activityLink || '').trim()) {
    const parsed = parseChatActivityLink(activityLink)
    if ((targetChatId && parsed.chatId && targetChatId !== parsed.chatId) || (targetActiveId && targetActiveId !== parsed.activeId)) {
      throw new Error('填写的 ID 与活动链接不一致，请重新解析链接或清空链接后填写 ID。')
    }
    targetChatId ||= parsed.chatId
    targetActiveId ||= parsed.activeId
  }
  if (!targetChatId || !targetActiveId) throw new Error('请填写群聊 ID 和活动 ID，或解析官方活动链接。')
  if (![targetChatId, targetActiveId].every((id) => /^[1-9][0-9]{0,31}$/.test(id))) {
    throw new Error('群聊 ID 和活动 ID 必须为最多 32 位的正整数。')
  }
  return { chatId: targetChatId, activeId: targetActiveId }
}

export const normalizeChatActivities = (payload) => {
  const tasks = [payload?.data?.tasks, payload?.data, payload?.tasks].find(Array.isArray) || []
  return tasks.map((task) => ({
    ...task,
    chatId: String(task?.chatId || task?.chat_id || '').trim(),
    activeId: String(task?.activeId || task?.active_id || task?.aid || '').trim(),
    // Unknown types stay unknown. A missing type must never become normal.
    type: String(task?.type || 'unknown'),
  })).filter((task) => task.activeId)
}

export const chatActivityTypeLabel = (type) => ({
  normal: '普通签到',
  photo: '拍照签到',
  location: '位置签到',
  qrcode: '二维码签到',
  gesture: '手势签到',
  code: '签到码签到',
}[type] || '未知类型')
