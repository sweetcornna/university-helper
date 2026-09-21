import { useState } from 'react'


export default function useTaskConfig() {


  const [speed, setSpeed] = useState(1.5)


  const [concurrency, setConcurrency] = useState(4)


  const [unopenedStrategy, setUnopenedStrategy] = useState('retry')


  // Ordered list of answer-bank providers; sent to the backend as a
  // comma-separated `provider` (单个=单题库，多个=按顺序回退). Default chain:
  // AI first: the owner answers with their own LLM API, and the AI provider is
  // the only link that can attempt a question it has never seen. 言溪 and GO题库
  // stay behind it as free fallbacks for questions the banks already know, so a
  // missing AI key degrades instead of failing. (The shared answer cache is
  // always consulted before any provider, so 本地缓存 here would be redundant.)
  const [tikuProvider, setTikuProvider] = useState(['AI', 'TikuYanxi', 'TikuGo'])


  const [tikuToken, setTikuToken] = useState('')


  // 自定义 AI 供应商配置（OpenAI 兼容协议）。仅当题库来源含 "AI" 时生效。
  // endpoint: 完整 chat completions 地址；key: API Key；model: 模型名。
  const [aiEndpoint, setAiEndpoint] = useState('')
  const [aiKey, setAiKey] = useState('')
  const [aiModel, setAiModel] = useState('')


  const [coverageThreshold, setCoverageThreshold] = useState(0.9)


  const [correctOptions, setCorrectOptions] = useState('对,正确,是')


  const [wrongOptions, setWrongOptions] = useState('错,错误,否')


  const [submitMode, setSubmitMode] = useState('submit')


  const [notifyService, setNotifyService] = useState('')


  const [notifyUrl, setNotifyUrl] = useState('')


  return {
    speed, setSpeed,
    concurrency, setConcurrency,
    unopenedStrategy, setUnopenedStrategy,
    tikuProvider, setTikuProvider,
    tikuToken, setTikuToken,
    aiEndpoint, setAiEndpoint,
    aiKey, setAiKey,
    aiModel, setAiModel,
    coverageThreshold, setCoverageThreshold,
    correctOptions, setCorrectOptions,
    wrongOptions, setWrongOptions,
    submitMode, setSubmitMode,
    notifyService, setNotifyService,
    notifyUrl, setNotifyUrl,
  }


}
