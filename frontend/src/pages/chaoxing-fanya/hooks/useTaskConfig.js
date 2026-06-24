import { useState } from 'react'


export default function useTaskConfig() {


  const [speed, setSpeed] = useState(1.5)


  const [concurrency, setConcurrency] = useState(4)


  const [unopenedStrategy, setUnopenedStrategy] = useState('retry')


  // Ordered list of answer-bank providers; sent to the backend as a
  // comma-separated `provider` (单个=单题库，多个=按顺序回退). Default chain:
  // 言溪 first (best, if a token is set), then the free GO题库 — so 答题 still
  // works without a Token. (The shared answer cache is always consulted first,
  // so adding 本地缓存 as an extra link would be redundant.)
  const [tikuProvider, setTikuProvider] = useState(['TikuYanxi', 'TikuGo'])


  const [tikuToken, setTikuToken] = useState('')


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
    coverageThreshold, setCoverageThreshold,
    correctOptions, setCorrectOptions,
    wrongOptions, setWrongOptions,
    submitMode, setSubmitMode,
    notifyService, setNotifyService,
    notifyUrl, setNotifyUrl,
  }


}
