import { useState } from 'react'


export default function useTaskConfig() {


  const [speed, setSpeed] = useState(1.5)


  const [concurrency, setConcurrency] = useState(4)


  const [unopenedStrategy, setUnopenedStrategy] = useState('retry')


  const [tikuProvider, setTikuProvider] = useState('TikuYanxi')


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
