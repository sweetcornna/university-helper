import { useEffect, useState, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { BookOpen, CheckCircle, GraduationCap, LogOut } from 'lucide-react'
import { getToken, getShuakeToken, isAuthenticated, removeToken, setShuakeToken } from '../utils/auth'
import { api } from '../utils/api'

/* ------------------------------------------------------------------ */
/*  Orbital-bubble dashboard                                          */
/* ------------------------------------------------------------------ */

const SERVICES = [
  {
    title: '学习通签到',
    desc: '智能签到服务',
    icon: CheckCircle,
    path: '/chaoxing-signin',
    gradient: 'from-blue-400 to-blue-600',
    glow: 'rgba(59,130,246,.45)',
    bg: 'rgba(59,130,246,.12)',
  },
  {
    title: '学习通泛雅',
    desc: '课程学习服务',
    icon: BookOpen,
    path: '/chaoxing-fanya',
    gradient: 'from-emerald-400 to-emerald-600',
    glow: 'rgba(52,211,153,.45)',
    bg: 'rgba(52,211,153,.12)',
  },
  {
    title: '智慧树',
    desc: '智慧树学习服务',
    icon: GraduationCap,
    path: '/zhihuishu-panel',
    gradient: 'from-violet-400 to-violet-600',
    glow: 'rgba(139,92,246,.45)',
    bg: 'rgba(139,92,246,.12)',
  },
]

/* radius of the orbit (responsive) */
const useOrbitRadius = () => {
  const [r, setR] = useState(140)
  useEffect(() => {
    const update = () => setR(window.innerWidth < 640 ? 110 : 140)
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])
  return r
}

export default function Dashboard() {
  const navigate = useNavigate()
  const orbitRadius = useOrbitRadius()

  /* ---------- auth guard ---------- */
  useEffect(() => {
    if (!isAuthenticated()) { navigate('/login'); return }
    const ensureShuakeToken = async () => {
      if (getShuakeToken()) return
      try {
        const resp = await api('/auth/shuake-token', { method: 'GET' })
        if (resp?.shuake_token) { setShuakeToken(resp.shuake_token); return }
      } catch (_) { /* fallback */ }
      const token = getToken()
      if (token) setShuakeToken(token)
    }
    ensureShuakeToken()
  }, [navigate])

  /* ---------- orbit animation ---------- */
  const angleRef = useRef(0)
  const rafRef = useRef(null)
  const [positions, setPositions] = useState(() =>
    SERVICES.map((_, i) => {
      const a = (i * 2 * Math.PI) / 3 - Math.PI / 2
      return { x: Math.cos(a), y: Math.sin(a) }
    }),
  )
  const [paused, setPaused] = useState(false)
  const [hovered, setHovered] = useState(-1)

  const tick = useCallback(() => {
    if (!paused) {
      angleRef.current += 0.003          // slow, dreamy rotation
      const base = angleRef.current
      setPositions(
        SERVICES.map((_, i) => {
          const a = base + (i * 2 * Math.PI) / 3
          return { x: Math.cos(a), y: Math.sin(a) }
        }),
      )
    }
    rafRef.current = requestAnimationFrame(tick)
  }, [paused])

  useEffect(() => {
    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [tick])

  /* ---------- click → expand → navigate ---------- */
  const [expanding, setExpanding] = useState(null)   // index | null
  const [expandStyle, setExpandStyle] = useState({})

  const handleClick = (index) => {
    if (expanding !== null) return
    setPaused(true)
    setExpanding(index)

    // bubble rect → full viewport transition
    const el = document.getElementById(`bubble-${index}`)
    if (el) {
      const rect = el.getBoundingClientRect()
      setExpandStyle({
        position: 'fixed',
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
        borderRadius: '50%',
        zIndex: 100,
        transition: 'all 0.7s cubic-bezier(.4,0,.2,1)',
      })

      // force reflow, then expand
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          setExpandStyle((prev) => ({
            ...prev,
            left: 0,
            top: 0,
            width: '100vw',
            height: '100vh',
            borderRadius: '0',
            opacity: 1,
          }))
        })
      })
    }

    setTimeout(() => navigate(SERVICES[index].path), 650)
  }

  const handleLogout = () => { removeToken(); navigate('/login') }

  /* ---------- render ---------- */
  return (
    <div className="relative min-h-screen overflow-hidden bg-gradient-to-br from-slate-50 via-blue-50/40 to-violet-50/30">

      {/* soft ambient blobs */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-32 -left-32 h-96 w-96 rounded-full bg-blue-200/30 blur-3xl" />
        <div className="absolute -bottom-32 -right-32 h-96 w-96 rounded-full bg-violet-200/30 blur-3xl" />
        <div className="absolute top-1/2 left-1/2 h-64 w-64 -translate-x-1/2 -translate-y-1/2 rounded-full bg-emerald-200/20 blur-3xl" />
      </div>

      {/* top bar */}
      <nav className="relative z-20 flex items-center justify-between px-6 py-4">
        <h1 className="text-lg font-bold tracking-tight text-text/80">刷课平台</h1>
        <button
          onClick={handleLogout}
          className="flex items-center gap-1.5 rounded-full border border-white/40 bg-white/50 px-4 py-2 text-sm text-text/70 backdrop-blur-md transition-all hover:bg-white/80 hover:text-text cursor-pointer"
        >
          <LogOut className="h-3.5 w-3.5" />
          退出
        </button>
      </nav>

      {/* centre stage */}
      <div className="relative z-10 flex flex-col items-center justify-center" style={{ minHeight: 'calc(100vh - 72px)' }}>

        {/* centre label */}
        <div className="pointer-events-none absolute flex flex-col items-center gap-1 select-none">
          <span className="text-xs font-medium uppercase tracking-widest text-text/30">选择服务</span>
        </div>

        {/* orbital ring visual */}
        <div
          className="absolute rounded-full border border-dashed border-slate-200/60"
          style={{ width: orbitRadius * 2 + 120, height: orbitRadius * 2 + 120 }}
        />

        {/* bubbles */}
        {SERVICES.map((svc, i) => {
          const isExpanding = expanding === i
          const isOther = expanding !== null && expanding !== i
          const pos = positions[i]
          const isHov = hovered === i

          return (
            <div
              key={svc.path}
              id={`bubble-${i}`}
              onClick={() => handleClick(i)}
              onMouseEnter={() => { setHovered(i); setPaused(true) }}
              onMouseLeave={() => { setHovered(-1); setPaused(false) }}
              className="absolute cursor-pointer select-none"
              style={{
                transform: `translate(${pos.x * orbitRadius}px, ${pos.y * orbitRadius}px) scale(${isHov ? 1.12 : 1})`,
                opacity: isOther ? 0 : 1,
                transition: isExpanding
                  ? 'none'
                  : 'transform 0.45s cubic-bezier(.4,0,.2,1), opacity 0.5s ease',
                zIndex: isHov ? 10 : 1,
              }}
            >
              {/* glow ring */}
              <div
                className="absolute inset-0 rounded-full blur-xl transition-opacity duration-500"
                style={{
                  background: svc.glow,
                  opacity: isHov ? 0.6 : 0.2,
                  transform: 'scale(1.3)',
                }}
              />

              {/* bubble body */}
              <div
                className={`relative flex flex-col items-center justify-center rounded-full border border-white/50 backdrop-blur-xl transition-shadow duration-500 ${
                  isHov ? 'shadow-2xl' : 'shadow-lg'
                }`}
                style={{
                  width: 120,
                  height: 120,
                  background: `linear-gradient(135deg, rgba(255,255,255,.85), rgba(255,255,255,.55))`,
                }}
              >
                {/* icon circle */}
                <div
                  className={`mb-1.5 flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br ${svc.gradient} shadow-md`}
                >
                  <svc.icon className="h-5 w-5 text-white" />
                </div>
                <span className="text-xs font-bold text-text/90">{svc.title}</span>
                <span className="text-[10px] text-text/50">{svc.desc}</span>
              </div>
            </div>
          )
        })}
      </div>

      {/* expanding overlay */}
      {expanding !== null && (
        <div
          className={`pointer-events-none bg-gradient-to-br ${SERVICES[expanding].gradient}`}
          style={expandStyle}
        />
      )}
    </div>
  )
}
