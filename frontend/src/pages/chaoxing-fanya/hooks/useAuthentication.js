import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { isAuthenticated, removeToken } from '../../../utils/auth'
import { api } from '../../../utils/api'
import { readLastUsername, saveLastUsername } from '../../../utils/chaoxingCreds'
import { TOKEN_ERROR } from '../utils'


// A 401/403 out of a /chaoxing/* endpoint is CHAOXING asking for its own login,
// not our app session expiring — api.js only wipes the app token for app-JWT
// 401s (see APP_JWT_401_PATTERN there, F62). So when one of these reaches us the
// server-held Chaoxing session is gone and the credential form has to come back.
const CHAOXING_SESSION_LOST =
  /(未登录|请先登录|登录已过期|登录状态已失效|登录态已失效|not logged in|please login|session expired)/i

const isChaoxingSessionLost = (err) => {
  const status = Number(err?.status)
  if (status === 401 || status === 403) return true
  return CHAOXING_SESSION_LOST.test(String(err?.message || ''))
}


export default function useAuthentication({ stopPolling }) {


  const navigate = useNavigate()


  // Recall the account shared with the signin page so it isn't retyped here.
  const [username, setUsername] = useState(readLastUsername)


  const [password, setPassword] = useState('')


  const [loginLoading, setLoginLoading] = useState(false)


  const [courses, setCourses] = useState([])


  const [error, setError] = useState('')


  const [notice, setNotice] = useState('')


  // The server can already hold a usable Chaoxing session for this platform
  // user, in which case the password must not be asked for again.
  // 'probing' → the mount-time GET /chaoxing/session is still in flight;
  // 'active'  → the server confirmed a session, so the form is skipped;
  // 'inactive'→ no session, OR the probe failed / 404'd / timed out. Anything
  // other than a confirmed session falls back to the credential form, so a
  // backend without these endpoints leaves the page exactly as it was.
  const [sessionStatus, setSessionStatus] = useState('probing')


  const [sessionUsername, setSessionUsername] = useState('')


  const [sessionExpiresAt, setSessionExpiresAt] = useState('')


  const [switchLoading, setSwitchLoading] = useState(false)


  // Set when an action still needs the raw credentials (starting a task posts
  // them to /course/start) while a server session is active — it brings the
  // hidden form back instead of dead-ending the user.
  const [credentialsRequired, setCredentialsRequired] = useState(false)


  // Persist the account so the signin page recalls it too.
  useEffect(() => {
    saveLastUsername(username)
  }, [username])


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


  // `callApi` takes full `/api/v1`-relative paths, while the shared Chaoxing
  // hooks speak paths relative to the Chaoxing API root (`/qr-login`). Prefixing
  // here keeps that convention in one place — passing bare `callApi` to them
  // silently targeted `/api/v1/qr-login`, which is a 405.
  const callChaoxingApi = useCallback(
    (path, options = {}) => callApi(`/chaoxing${path}`, options),
    [callApi]
  )


  const loadCourses = useCallback(async () => {

    try {

      const resp = await callApi('/chaoxing/courses')


      if (!resp) return


      const list = Array.isArray(resp?.courses) ? resp.courses : Array.isArray(resp?.data) ? resp.data : []


      setCourses(list)


      setNotice(list.length > 0 ? `已获取 ${list.length} 门课程。` : '未查询到课程。')

    } catch (err) {

      // The session we trusted died mid-session: drop back to the form and say
      // why, rather than leaving an empty list with no way to recover.
      if (isChaoxingSessionLost(err)) {

        setSessionStatus('inactive')

        setSessionUsername('')

        setSessionExpiresAt('')

        setCourses([])

        setError('学习通登录态已失效，请重新输入账号密码登录。')

        return

      }

      setError(err?.message || '获取课程失败，请稍后重试。')

    }

  }, [callApi])


  // Probe the server-held session once on mount. `probedRef` keeps this to a
  // single request even if the callbacks below are re-created (and under
  // StrictMode's double-invoked effects).
  const probedRef = useRef(false)


  useEffect(() => {

    if (probedRef.current) return

    probedRef.current = true

    const probe = async () => {

      try {

        const resp = await callApi('/chaoxing/session', { timeoutMs: 8000 })

        if (resp?.active) {

          const account = String(resp.username || '').trim()

          setSessionUsername(account)

          setSessionExpiresAt(String(resp.expires_at || ''))

          // /course/start still posts the account, so keep the field in sync.
          if (account) setUsername(account)

          setSessionStatus('active')

          await loadCourses()

          return

        }

        setSessionStatus('inactive')

      } catch {

        // Fail open. A backend without /chaoxing/session, a timeout, or a 200
        // carrying the SPA's index.html (the backend serves that for any
        // unmatched GET, so a missing route is NOT a 404) must all land on the
        // credential form.
        setSessionStatus('inactive')

      }

    }

    // Deliberately no `cancelled` flag. `probedRef` already guarantees exactly
    // one probe for the component's lifetime, so a cancel-on-unmount guard
    // would discard the ONLY result: StrictMode mounts, unmounts (cancel), then
    // remounts, and the remounted effect returns early on the ref — leaving
    // sessionStatus stuck on 'probing' forever and the login form never shown.
    void probe()

  }, [callApi, loadCourses])


  // The "切换账号" action: forget the server session and come back to the form
  // even when the server can't be reached, so the button never looks stuck.
  const switchAccount = useCallback(async () => {

    setSwitchLoading(true)

    setError('')

    setNotice('')

    try {

      await callApi('/chaoxing/session', { method: 'DELETE' })

      setNotice('已退出当前学习通账号，请使用新账号登录。')

    } catch (err) {

      setError(err?.message || '退出登录失败，重新登录将覆盖当前会话。')

    } finally {

      setSessionStatus('inactive')

      setSessionUsername('')

      setSessionExpiresAt('')

      setCourses([])

      setPassword('')

      setCredentialsRequired(false)

      setSwitchLoading(false)

    }

  }, [callApi])


  // Bring the credential form back for an action that needs the raw password
  // even though a server session exists (see credentialsRequired above).
  const requireCredentials = useCallback(() => {

    setCredentialsRequired(true)

    setError(
      sessionStatus === 'active'
        ? '启动任务仍需验证一次账号密码，请在上方表单中填写后重试。'
        : '请先填写账号和密码。'
    )

  }, [sessionStatus])


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


        // A fresh password login IS the session — record it so the form gives
        // way to the status line, even on a backend without /chaoxing/session.
        setSessionUsername(username.trim())


        setSessionExpiresAt(String(loginResp?.expires_at || loginResp?.expiresAt || ''))


        setSessionStatus('active')


        setCredentialsRequired(false)


        await loadCourses()


      } catch (err) {


        setError(err?.message || '登录失败。')


      } finally {


        setLoginLoading(false)


      }


    },


    [callApi, loadCourses, password, username]


  )


  // A confirmed QR scan produces the SAME server-held session a password login
  // does, so it lands in exactly the same state — which is what lets the 签到
  // page inherit this login without asking for the password again.
  const handleQrSuccess = useCallback(
    (resp) => {
      const account = String(resp?.username || '').trim()
      if (account) {
        setSessionUsername(account)
        // Keep the form field in sync: /course/start still posts the account,
        // and the backend binds the reused session to it.
        setUsername(account)
      }
      setSessionExpiresAt('')
      setSessionStatus('active')
      setCredentialsRequired(false)
      setError('')
      setNotice('扫码登录成功。')
      void loadCourses()
    },
    [loadCourses]
  )

  // The authenticated view is shown when the server confirms a session OR when
  // a password login already produced courses — the latter keeps the page
  // working against a backend that has no /chaoxing/session endpoint.
  const authenticated = sessionStatus === 'active' || courses.length > 0


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
    sessionStatus,
    sessionUsername,
    sessionExpiresAt,
    switchAccount,
    switchLoading,
    credentialsRequired,
    requireCredentials,
    callChaoxingApi,
    handleQrSuccess,
    authenticated,
  }


}
