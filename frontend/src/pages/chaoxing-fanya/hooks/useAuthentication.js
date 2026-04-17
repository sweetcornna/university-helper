import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { isAuthenticated, removeToken } from '../../../utils/auth'
import { api } from '../../../utils/api'
import { TOKEN_ERROR } from '../utils'


export default function useAuthentication({ stopPolling }) {


  const navigate = useNavigate()


  const [username, setUsername] = useState('')


  const [password, setPassword] = useState('')


  const [loginLoading, setLoginLoading] = useState(false)


  const [courses, setCourses] = useState([])


  const [error, setError] = useState('')


  const [notice, setNotice] = useState('')


  useEffect(() => {


    if (!isAuthenticated()) {


      navigate('/login', { replace: true })


    }


  }, [navigate])


  const onAuthError = useCallback(


    (message) => {


      if (TOKEN_ERROR.test(String(message || ''))) {


        stopPolling()


        removeToken()


        navigate('/login', { replace: true })


        return true


      }


      return false


    },


    [navigate, stopPolling]


  )


  const callApi = useCallback(


    async (endpoint, options = {}) => {


      try {


        return await api(endpoint, options)


      } catch (err) {


        const message = err?.message || '请求失败'


        if (onAuthError(message)) return null


        throw err


      }


    },


    [onAuthError]


  )


  const loadCourses = useCallback(async () => {


    const resp = await callApi('/chaoxing/courses')


    if (!resp) return


    const list = Array.isArray(resp?.courses) ? resp.courses : Array.isArray(resp?.data) ? resp.data : []


    setCourses(list)


    setNotice(list.length > 0 ? `已获取 ${list.length} 门课程。` : '未查询到课程。')


  }, [callApi])


  const handleLogin = useCallback(


    async (event) => {


      event.preventDefault()


      setError('')


      setNotice('')


      if (!username.trim() || !password.trim()) {


        setError('请输入超星账号和密码。')


        return


      }


      setLoginLoading(true)


      try {


        const loginResp = await callApi('/chaoxing/login', {


          method: 'POST',


          body: JSON.stringify({ username: username.trim(), password })


        })


        if (!loginResp) return


        await loadCourses()


      } catch (err) {


        setError(err?.message || '登录失败。')


      } finally {


        setLoginLoading(false)


      }


    },


    [callApi, loadCourses, password, username]


  )


  return {
    username, setUsername,
    password, setPassword,
    loginLoading,
    courses, setCourses,
    error, setError,
    notice, setNotice,
    callApi,
    handleLogin,
    loadCourses,
  }


}
