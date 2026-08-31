import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { isAuthenticated, removeToken } from '../../../utils/auth'
import { api } from '../../../utils/api'
import { readLastUsername, saveLastUsername } from '../../../utils/chaoxingCreds'
import { TOKEN_ERROR } from '../utils'


export default function useAuthentication({ stopPolling }) {


  const navigate = useNavigate()


  // Recall the account shared with the signin page so it isn't retyped here.
  const [username, setUsername] = useState(readLastUsername)


  const [password, setPassword] = useState('')


  const [loginLoading, setLoginLoading] = useState(false)


  const [courses, setCourses] = useState([])


  const [error, setError] = useState('')


  const [notice, setNotice] = useState('')


  const mountedRef = useRef(true)
  const courseRequestIdRef = useRef(0)
  const [coursesLoading, setCoursesLoading] = useState(false)


  // Persist the account so the signin page recalls it too.
  useEffect(() => {
    saveLastUsername(username)
  }, [username])


  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      courseRequestIdRef.current += 1
    }
  }, [])


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
    const requestId = courseRequestIdRef.current + 1
    courseRequestIdRef.current = requestId
    const isCurrentRequest = () => (
      mountedRef.current && courseRequestIdRef.current === requestId
    )

    if (!isCurrentRequest()) return

    setError('')
    setNotice('')
    setCoursesLoading(true)

    try {
      const resp = await callApi('/chaoxing/courses')

      if (!resp || !isCurrentRequest()) return

      const list = Array.isArray(resp?.courses) ? resp.courses : Array.isArray(resp?.data) ? resp.data : []

      if (!isCurrentRequest()) return
      setCourses(list)
      setNotice(list.length > 0 ? `已获取 ${list.length} 门课程。` : '未查询到课程。')
    } catch (err) {
      if (isCurrentRequest()) setError(err?.message || '获取课程失败。')
    } finally {
      if (isCurrentRequest()) setCoursesLoading(false)
    }
  }, [callApi])


  const handleLogin = useCallback(


    async (event) => {


      event.preventDefault()


      if (!mountedRef.current) return


      const loginUsername = username.trim()
      const loginPassword = password
      setError('')


      setNotice('')


      if (!loginUsername || !loginPassword.trim()) {


        setError('请输入超星账号和密码。')


        return


      }


      setLoginLoading(true)


      try {


        const loginResp = await callApi('/chaoxing/login', {


          method: 'POST',


          body: JSON.stringify({ username: loginUsername, password: loginPassword })


        })


        if (!loginResp || !mountedRef.current) return


        setUsername(loginUsername)
        setPassword(loginPassword)
        await loadCourses()


      } catch (err) {


        if (mountedRef.current) setError(err?.message || '登录失败。')


      } finally {


        if (mountedRef.current) setLoginLoading(false)


      }


    },


    [callApi, loadCourses, password, username]


  )


  return {
    username, setUsername,
    password, setPassword,
    loginLoading,
    coursesLoading,
    courses, setCourses,
    error, setError,
    notice, setNotice,
    callApi,
    handleLogin,
    loadCourses,
  }


}
