import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowRight,
  BookOpen,
  CheckCircle,
  AlertCircle,
  CircleDashed,
  GraduationCap,
  Loader2,
  Lock,
  WifiOff,
  XCircle,
} from 'lucide-react'
import { PageHeader, StatusBadge, useRuntimeProfile } from '../components'
import { getShuakeToken, getToken, setShuakeToken } from '../utils/auth'
import { api } from '../utils/api'

const SERVICE_DEFINITIONS = [
  {
    id: 'signin',
    platform: '学习通',
    name: '课堂签到',
    path: '/chaoxing-signin',
    taskPath: '/chaoxing-signin?tab=history',
    icon: CheckCircle,
    spine: 'signin',
  },
  {
    id: 'fanya',
    platform: '学习通',
    name: '课程学习',
    path: '/chaoxing-fanya',
    taskPath: '/chaoxing-fanya?tab=tasks',
    icon: BookOpen,
    spine: 'fanya',
  },
  {
    id: 'zhihuishu',
    platform: '智慧树',
    name: '课程学习',
    path: '/zhihuishu-panel',
    taskPath: '/zhihuishu-panel?tab=tasks',
    icon: GraduationCap,
    spine: 'zhihuishu',
  },
].map((service) => ({ ...service, title: `${service.platform} ${service.name}` }))

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

// Why a service's task list could not be read. Permission, network and server
// failures read differently so the student knows whether to log in again,
// check the connection or simply wait.
const describeFailure = (reason) => {
  const status = Number(reason?.status)
  if (status === 401 || status === 403) return { kind: 'permission', text: '无权限读取任务', icon: Lock }
  if (status === 0 || reason instanceof TypeError) return { kind: 'network', text: '网络连接失败', icon: WifiOff }
  if (status >= 500) return { kind: 'server', text: '服务暂不可用', icon: XCircle }
  return { kind: 'error', text: '任务读取失败', icon: XCircle }
}

const formatToday = () => {
  try {
    return new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(new Date())
  } catch (_) {
    return ''
  }
}

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
    failures: {},
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
      const failures = Object.fromEntries(
        results
          .map((result, index) => [taskRequests[index].serviceId, result])
          .filter(([, result]) => result.status === 'rejected')
          .map(([serviceId, result]) => [serviceId, describeFailure(result.reason)])
      )
      setSnapshot({ loading: false, outcomes, failures, tasks })
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

  const syncTone = snapshot.loading
    ? 'text-text-muted'
    : fulfilledCount === SERVICE_DEFINITIONS.length
      ? 'text-success'
      : fulfilledCount > 0
        ? 'text-warning'
        : 'text-danger'
  const SyncIcon = snapshot.loading
    ? Loader2
    : fulfilledCount === SERVICE_DEFINITIONS.length
      ? CheckCircle
      : AlertCircle

  return (
    <div className="space-y-6">
      <PageHeader
        spine="home"
        title="今日任务"
        description={formatToday() || undefined}
        actions={(
          <p role="status" aria-live="polite" className={`inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs font-semibold ${syncTone}`}>
            <SyncIcon className={`h-3.5 w-3.5 ${snapshot.loading ? 'motion-safe:animate-spin' : ''}`} aria-hidden="true" />
            {syncStatus}
          </p>
        )}
      />

      {selectedTaskRecord && (
        <section aria-labelledby="next-step-heading" className={`spine-${selectedService?.spine || 'home'}`}>
          <div className="ui-index-card flex flex-col justify-between gap-4 p-5 sm:flex-row sm:items-center">
            <div className="flex min-w-0 items-start gap-4">
              <span className="spine-chip mt-1 h-10 w-2" aria-hidden="true" />
              <div className="min-w-0">
                <h2 id="next-step-heading" className="font-display text-lg font-bold text-text">
                  {activeTaskRecord ? '查看运行进度' : '处理最近失败'}
                </h2>
                <p className="mt-1 truncate text-sm text-text-muted">
                  {selectedService?.title} · {taskTitle(selectedTaskRecord.task)}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => navigate(selectedService.taskPath)}
              className={`${activeTaskRecord ? 'ui-btn-primary' : 'ui-btn-cta'} ui-btn-lg shrink-0 justify-between gap-6 sm:min-w-40`}
            >
              {activeTaskRecord ? '查看任务' : '前往恢复'}
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </section>
      )}

      <section aria-labelledby="service-heading">
        <h2 id="service-heading" className="font-display mb-3 text-base font-bold text-text">课程服务</h2>

        <div className="grid gap-4 md:grid-cols-3">
          {SERVICE_DEFINITIONS.map((service) => {
            const Icon = service.icon
            const serviceTasks = snapshot.tasks.filter(
              ({ serviceId }) => serviceId === service.id
            )
            const serviceTaskRecord =
              newestTaskRecord(serviceTasks, TASK_ACTIVE) ||
              newestTaskRecord(serviceTasks, TASK_FAILED)
            const failure = snapshot.failures[service.id]
            const FailureIcon = failure?.icon
            return (
              <button
                key={service.id}
                type="button"
                aria-labelledby={`service-${service.id}-heading`}
                aria-describedby={`service-${service.id}-state`}
                onClick={() => navigate(service.path)}
                className={`spine-${service.spine} ui-card group relative flex flex-col overflow-hidden p-0 text-left hover:border-primary/50 focus-visible:ring-offset-2`}
              >
                <span className="block h-1.5 w-full" style={{ background: 'rgb(var(--spine))' }} aria-hidden="true" />
                <span className="flex flex-1 flex-col p-4">
                  <span className="flex items-start justify-between gap-3">
                    <span className="grid h-8 w-8 place-items-center rounded-md text-on-spine" style={{ background: 'rgb(var(--spine))' }} aria-hidden="true">
                      <Icon className="h-4 w-4" />
                    </span>
                    {serviceTaskRecord && (
                      <StatusBadge status={taskStatus(serviceTaskRecord.task)} />
                    )}
                  </span>
                  <h3 id={`service-${service.id}-heading`} className="font-display mt-3 text-base font-bold text-text">
                    <span className="text-text-muted">{service.platform}</span> {service.name}
                  </h3>
                  <span className="mt-4 flex items-center justify-between gap-2 border-t border-border-subtle pt-3 text-xs">
                    <span id={`service-${service.id}-state`} className={`inline-flex items-center gap-1.5 ${failure ? (failure.kind === 'permission' ? 'text-warning' : 'text-danger') : 'text-text-muted'}`}>
                      {snapshot.loading ? (
                        <><Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin" aria-hidden="true" />同步中</>
                      ) : failure ? (
                        <><FailureIcon className="h-3.5 w-3.5" aria-hidden="true" />{failure.text}</>
                      ) : serviceTasks.length === 0 ? (
                        <><CircleDashed className="h-3.5 w-3.5" aria-hidden="true" />暂无任务记录</>
                      ) : (
                        <><CheckCircle className="h-3.5 w-3.5" aria-hidden="true" />共 {serviceTasks.length} 条任务记录</>
                      )}
                    </span>
                    <span className="inline-flex items-center gap-1 font-semibold text-primary" aria-hidden="true">
                      进入<ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
                    </span>
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      </section>

      {/* The next-step card already shows the running task (or, with none
          running, the newest failure); only a failure hidden behind a running
          task gets its own line. */}
      {activeTaskRecord && failedTaskRecord && (
        <section aria-label="最近失败">
          <button
            type="button"
            onClick={() => navigate(failedService.taskPath)}
            className="ui-panel flex w-full items-center gap-3 px-4 py-3 text-left hover:border-danger/40"
          >
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-danger-surface text-danger"><AlertCircle className="h-4 w-4" aria-hidden="true" /></span>
            <span className="min-w-0">
              <span className="catalog-label block">最近失败</span>
              <span className="mt-0.5 block truncate text-sm font-semibold text-text">
                {failedService?.title} · {taskTitle(failedTaskRecord.task)}
              </span>
            </span>
          </button>
        </section>
      )}
    </div>
  )
}
