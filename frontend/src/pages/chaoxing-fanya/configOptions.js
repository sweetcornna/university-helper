// Option lists shared by 学习配置 and the start bar summary.

export const UNOPENED_STRATEGIES = [
  { value: 'retry', label: '等待重试' },
  { value: 'continue', label: '跳过' },
  { value: 'ask', label: '手动处理' },
]

export const SUBMIT_MODES = [
  { value: 'submit', label: '自动提交' },
  { value: 'save', label: '仅保存' },
]

export const TIKU_PROVIDERS = [
  { value: 'TikuYanxi', label: '言溪题库', short: '言溪', hint: '通用题库（需 Token）' },
  { value: 'TikuGo', label: 'GO 题库', short: 'GO', hint: '免费搜题源' },
  { value: 'TikuLike', label: 'Like 题库', short: 'Like', hint: '备用题库（需 Token）' },
  { value: 'TikuAdapter', label: '题库适配器', short: '适配器', hint: '需要服务地址' },
  { value: 'AI', label: 'AI 智能答题', short: 'AI', hint: '需要服务地址' },
  { value: 'SiliconFlow', label: '硅基流动', short: '硅基流动', hint: 'AI 服务（需 Token）' },
  { value: 'LocalCache', label: '本地缓存', short: '本地缓存', hint: '仅用已缓存答案' },
]

// Providers that need a public endpoint URL the web UI cannot set yet; the
// backend rejects a start request that selects them (422).
export const ENDPOINT_PROVIDERS = new Set(['TikuAdapter', 'AI'])

export const providerList = (value) => (Array.isArray(value) ? value : [value]).filter(Boolean)

export const providerLabel = (value, key = 'label') =>
  TIKU_PROVIDERS.find((option) => option.value === value)?.[key] || value

export const configSummary = ({ speed, concurrency, tikuProvider }) => {
  const providers = providerList(tikuProvider)
  const tiku = providers.length > 0 ? providers.map((value) => providerLabel(value, 'short')).join(' → ') : '不答题'
  return `${Number(speed).toFixed(1)} 倍速 · ${concurrency} 个并发章节 · 题库 ${tiku}`
}
