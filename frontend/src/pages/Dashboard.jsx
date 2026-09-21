import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowRight,
  BookOpen,
  CheckCircle,
  AlertCircle,
  GraduationCap,
  RefreshCw,
} from 'lucide-react'
import { Card, StatusBadge, useRuntimeProfile } from '../components'
import { getShuakeToken, getToken, setShuakeToken } from '../utils/auth'
import { api } from '../utils/api'

const SERVICE_DEFINITIONS = [
  {
    id: 'signin',
    title: '学习通签到',
    path: '/chaoxing-signin',
    icon: CheckCircle,
  },
  {
    id: 'fanya',
    title: '学习通泛雅',
    path: '/chaoxing-fanya',
    icon: BookOpen,
  },
  {
    id: 'zhihuishu',
    title: '智慧树',
    path: '/zhihuishu-panel',
    icon: GraduationCap,
  },
]

const TASK_ACTIVE = new Set([
  'running',
  'started',
  'starting',
  'pending',
  'queued',
  'processing',
  'in_progress',
  'paused',
  'cancelling',
])
const TASK_FAILED = new Set(['failed', 'error'])

const toTaskArray = (payload) => {
  const candidates = [payload?.tasks, payload?.data?.tasks, payload?.data, payload?.result, payload]
  return candidates.find(Array.isArray) || []
}

const taskStatus = (task) => String(task?.status || task?.state || '').toLowerCase()
const taskTitle = (task) => task?.course_name || task?.courseName || task?.name || task?.title || '未命名课程'

const toTimestamp = (value) => {
  if (value === undefined || value === null || value === '') return 0
  const numeric = Number(value)
  if (Number.isFinite(numeric)) return numeric > 0 && numeric < 1e12 ? numeric * 1000 : numeric
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? 0 : parsed
}

const taskTimestamp = (task) => {
  const candidates = [
    task?.updated_at,
    task?.updatedAt,
    task?.started_at,
    task?.startedAt,
    task?.created_at,
    task?.createdAt,
  ]
  for (const candidate of candidates) {
    const timestamp = toTimestamp(candidate)
    if (timestamp > 0) return timestamp
  }
  return 0
}

const newestTaskRecord = (records, statuses) =>
  records.reduce((newest, record) => {
    if (!statuses.has(taskStatus(record.task))) return newest
    if (!newest || taskTimestamp(record.task) > taskTimestamp(newest.task)) return record
    return newest
  }, null)

export default function Dashboard() {
  const navigate = useNavigate()
  const { isLocal } = useRuntimeProfile()
  const [snapshot, setSnapshot] = useState({
    loading: true,
    outcomes: {
      signin: 'pending',
      fanya: 'pending',
      zhihuishu: 'pending',
    },
    tasks: [],
  })

  useEffect(() => {
    let cancelled = false

    const bootstrap = async () => {
      if (!isLocal && !getShuakeToken()) {
        try {
          const response = await api('/auth/shuake-token', { method: 'GET' })
          if (response?.shuake_token) setShuakeToken(response.shuake_token)
        } catch (_) {
          const token = getToken()
          if (token) setShuakeToken(token)
        }
      }

      const taskRequests = [
        { serviceId: 'signin', request: api('/chaoxing/task-list', { method: 'GET', timeoutMs: 6000 }) },
        { serviceId: 'fanya', request: api('/course/tasks', { method: 'GET', timeoutMs: 6000 }) },
        { serviceId: 'zhihuishu', request: api('/course/zhihuishu/tasks', { method: 'GET', timeoutMs: 6000 }) },
      ]
      const results = await Promise.allSettled(taskRequests.map(({ request }) => request))
      if (cancelled) return

      const tasks = results.flatMap((result, index) => {
        if (result.status !== 'fulfilled') return []
        return toTaskArray(result.value).map((task) => ({
          serviceId: taskRequests[index].serviceId,
          task,
        }))
      })
      const outcomes = Object.fromEntries(
        results.map((result, index) => [taskRequests[index].serviceId, result.status])
      )
      setSnapshot({ loading: false, outcomes, tasks })
    }

    bootstrap()
    return () => {
      cancelled = true
    }
  }, [isLocal])

  const activeTaskRecord = newestTaskRecord(snapshot.tasks, TASK_ACTIVE)
  const failedTaskRecord = newestTaskRecord(snapshot.tasks, TASK_FAILED)
  const selectedTaskRecord = activeTaskRecord || failedTaskRecord
  const activeService = activeTaskRecord
    ? SERVICE_DEFINITIONS.find((service) => service.id === activeTaskRecord.serviceId)
    : null
  const failedService = failedTaskRecord
    ? SERVICE_DEFINITIONS.find((service) => service.id === failedTaskRecord.serviceId)
    : null
  const selectedService = activeService || failedService
  const fulfilledCount = Object.values(snapshot.outcomes).filter(
    (outcome) => outcome === 'fulfilled'
  ).length
  const syncStatus = snapshot.loading
    ? '正在同步'
    : fulfilledCount === SERVICE_DEFINITIONS.length
      ? '已同步任务'
      : fulfilledCount > 0
        ? '部分不可用'
        : '暂不可用'

  return (
    <div className="space-y-6 sm:space-y-8">
      <h1 className="text-3xl font-black leading-tight tracking-tight text-text sm:text-4xl">
        今日任务
      </h1>

      {selectedTaskRecord && (
        <section aria-labelledby="next-step-heading">
          <Card className="flex flex-col justify-between gap-6 bg-secondary text-background dark:text-text sm:flex-row sm:items-center" padding="spacious" tone="elevated">
            <div className="min-w-0">
              <h2 id="next-step-heading" className="text-2xl font-black">
                {activeTaskRecord ? '查看运行进度' : '处理最近失败'}
              </h2>
              <p className="mt-2 truncate text-sm font-semibold opacity-75">
                {selectedService?.title} · {taskTitle(selectedTaskRecord.task)}
              </p>
            </div>
            <button
              type="button"
              onClick={() => navigate(selectedService.path)}
              className="inline-flex min-h-[46px] shrink-0 items-center justify-between gap-6 rounded-xl bg-cta px-4 font-bold text-[#172033] hover:bg-cta/90 sm:min-w-44"
            >
              {activeTaskRecord ? '查看任务' : '前往恢复'}
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </Card>
        </section>
      )}

      <section aria-labelledby="service-heading">
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="service-heading" className="text-xl font-black text-text">课程服务</h2>
          <p role="status" aria-live="polite" className="text-sm font-semibold text-text-muted">
            {syncStatus}
          </p>
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          {SERVICE_DEFINITIONS.map((service) => {
            const Icon = service.icon
            const serviceTasks = snapshot.tasks.filter(
              ({ serviceId }) => serviceId === service.id
            )
            const serviceTaskRecord =
              newestTaskRecord(serviceTasks, TASK_ACTIVE) ||
              newestTaskRecord(serviceTasks, TASK_FAILED)
            return (
              <button
                key={service.id}
                type="button"
                aria-labelledby={`service-${service.id}-heading`}
                onClick={() => navigate(service.path)}
                className="relative overflow-hidden rounded-2xl border border-border bg-surface p-5 text-left shadow-sm transition-[transform,border-color,box-shadow] hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-lg focus-visible:ring-offset-2"
              >
                <div className="flex items-start justify-between gap-4">
                  <span className="grid h-11 w-11 place-items-center rounded-xl bg-primary/10 text-primary">
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </span>
                  {serviceTaskRecord && (
                    <StatusBadge status={taskStatus(serviceTaskRecord.task)} />
                  )}
                </div>
                <h3 id={`service-${service.id}-heading`} className="mt-5 text-lg font-black text-text">
                  {service.title}
                </h3>
              </button>
            )
          })}
        </div>
      </section>

      {(activeTaskRecord || failedTaskRecord) && (
        <section className="grid gap-4 md:grid-cols-2" aria-label="任务概览">
          {activeTaskRecord && (
            <Card padding="compact" tone="subtle">
              <div className="flex items-center gap-3">
                <span className="grid h-9 w-9 place-items-center rounded-lg bg-cta/15 text-warning"><RefreshCw className="h-4 w-4" aria-hidden="true" /></span>
                <div>
                  <p className="text-xs text-text-muted">当前运行</p>
                  <p className="mt-0.5 truncate text-sm font-bold text-text">
                    {activeService?.title} · {taskTitle(activeTaskRecord.task)}
                  </p>
                </div>
              </div>
            </Card>
          )}
          {failedTaskRecord && (
            <Card padding="compact" tone="subtle">
              <div className="flex items-center gap-3">
                <span className="grid h-9 w-9 place-items-center rounded-lg bg-danger-surface text-danger"><AlertCircle className="h-4 w-4" aria-hidden="true" /></span>
                <div>
                  <p className="text-xs text-text-muted">最近失败</p>
                  <p className="mt-0.5 truncate text-sm font-bold text-text">
                    {failedService?.title} · {taskTitle(failedTaskRecord.task)}
                  </p>
                </div>
              </div>
            </Card>
          )}
        </section>
      )}
    </div>
  )
}
