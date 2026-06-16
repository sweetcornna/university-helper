import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { BookOpen, CheckCircle, GraduationCap, ChevronRight } from 'lucide-react'
import { getToken, getShuakeToken, setShuakeToken } from '../utils/auth'
import { api } from '../utils/api'

/* ------------------------------------------------------------------ */
/*  Static service grid                                                */
/*                                                                     */
/*  Replaces the previous orbital layout where the three entry points  */
/*  rotated continuously — moving click targets that fought Fitts'     */
/*  law, ignored prefers-reduced-motion (the spin was rAF-driven), and */
/*  were awkward for keyboard / touch users. Static cards are easier   */
/*  to hit, fully accessible, and leave room for per-service status.   */
/* ------------------------------------------------------------------ */

const SERVICES = [
  {
    title: '学习通签到',
    desc: '智能签到 · 拍照 / 位置 / 二维码 / 手势 / 签到码',
    icon: CheckCircle,
    path: '/chaoxing-signin',
    accent: 'from-blue-400 to-blue-600',
  },
  {
    title: '学习通泛雅',
    desc: '课程视频自动学习与答题',
    icon: BookOpen,
    path: '/chaoxing-fanya',
    accent: 'from-emerald-400 to-emerald-600',
  },
  {
    title: '智慧树',
    desc: '知到课程视频学习与任务管理',
    icon: GraduationCap,
    path: '/zhihuishu-panel',
    accent: 'from-violet-400 to-violet-600',
  },
]

export default function Dashboard() {
  const navigate = useNavigate()

  /* ---------- shuake token bootstrap ---------- */
  // The route guard lives in App.jsx (PrivateRoute); unauthenticated users
  // never reach this effect. Token refresh on 401 is handled centrally by
  // utils/api.js → AuthExpiredListener.
  useEffect(() => {
    const ensureShuakeToken = async () => {
      if (getShuakeToken()) return
      try {
        const resp = await api('/auth/shuake-token', { method: 'GET' })
        if (resp?.shuake_token) {
          setShuakeToken(resp.shuake_token)
          return
        }
      } catch (_) {
        /* fallback */
      }
      const token = getToken()
      if (token) setShuakeToken(token)
    }
    ensureShuakeToken()
  }, [])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-text">选择服务</h1>
        <p className="mt-1 text-sm text-text-muted">挑选要使用的刷课 / 签到服务开始。</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {SERVICES.map((svc) => (
          <button
            key={svc.path}
            type="button"
            onClick={() => navigate(svc.path)}
            className="group flex items-start gap-4 rounded-2xl border border-border/60 bg-surface/80 p-5 text-left shadow-sm backdrop-blur-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
          >
            <span
              className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${svc.accent} text-white shadow-md`}
            >
              <svc.icon className="h-6 w-6" aria-hidden="true" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center justify-between gap-2">
                <span className="font-semibold text-text">{svc.title}</span>
                <ChevronRight className="h-4 w-4 shrink-0 text-text-muted transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
              </span>
              <span className="mt-1 block text-sm text-text-muted">{svc.desc}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
