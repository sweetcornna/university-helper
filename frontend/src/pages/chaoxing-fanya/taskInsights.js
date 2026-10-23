// Turns a raw Chaoxing learning task (status payload + log lines) into what
// the 执行与日志 view shows: a Chinese status, a one-line headline, and, when
// something went wrong, what happened and what to do next. Pure functions only.
import { normalizeStatus, taskStatusLabel, taskStatusTone } from '../../utils/taskStatus'
import { translateTaskMessage } from '../../utils/taskMessages'
import { normalizeCourseText, toNum } from './utils'

export const ACTION_LABELS = {
  relogin: '重新登录学习通',
  settings: '调整学习配置',
  courses: '重新选择课程',
  tasks: '查看运行中的任务',
  retry: '重新开始',
}

const ACTION_ORDER = ['relogin', 'settings', 'courses', 'tasks', 'retry']

const stripPeriod = (text) => String(text || '').trim().replace(/[。.]+$/, '')

// Per-chapter lines written by the backend (already Chinese).
const CHAPTER_RETRYING = /^章节「(.+?)」处理失败，正在自动重试（最多 (\d+) 次）。原因：(.*)$/
const CHAPTER_SKIPPED = /^章节「(.+?)」重试 (\d+) 次仍失败，已跳过。原因：(.*?)(?:。建议：(.*))?$/

export const parseChapterLog = (message) => {
  const text = String(message || '').trim()
  let match = text.match(CHAPTER_SKIPPED)
  if (match) {
    return { kind: 'skipped', chapter: match[1], tries: Number(match[2]), reason: stripPeriod(match[3]), hint: stripPeriod(match[4]) }
  }
  match = text.match(CHAPTER_RETRYING)
  if (match) return { kind: 'retrying', chapter: match[1], tries: Number(match[2]), reason: stripPeriod(match[3]) }
  return null
}

// Ordered: the first matching kind wins.
const KINDS = [
  { kind: 'login', test: /登录|login|password|密码/i, title: '学习通登录失败', hint: '在「账号」里重新登录学习通后再开始。', actions: ['relogin', 'retry'] },
  { kind: 'restart', test: /服务重启|service restart/i, title: '服务重启，任务被中断', hint: '服务刚重启过，重新开始任务即可。', actions: ['retry'] },
  { kind: 'noCourses', test: /都找不到了|No available courses/i, title: '找不到所选课程', hint: '在「选择课程」里刷新课程列表后重新选择。', actions: ['courses'] },
  { kind: 'chapterGone', test: /找不到你选的最后一节|no longer exists/i, title: '选的最后一节不在了', hint: '刷新这门课的章节列表，重新选择学到哪一节。', actions: ['courses'] },
  { kind: 'answers', test: /题库|答案|answer|tiku|token/i, title: '有题目没找到答案', hint: '在「学习配置」里换一个题库或填写题库 Token 后重试。', actions: ['settings', 'retry'] },
  { kind: 'notOpen', test: /未开放|未开启|待解锁|not open|locked|解锁/i, title: '有章节还没开放', hint: '前面的章节没完成时后面的不会开放。可在「学习配置」把「未开放章节」改为「跳过」。', actions: ['settings', 'retry'] },
  { kind: 'network', test: /超时|timeout|连不上|网络|request failed|请求失败|连接|50[234]/i, title: '连接学习通出了问题', hint: '学习通或网络暂时不稳定，稍后点「重新开始」。', actions: ['retry'] },
  { kind: 'server', test: /后台线程|background thread|保存任务状态|persist|意外出错|unexpected/i, title: '服务器出错，任务没有完成', hint: '稍后重试；一直出现请联系管理员，并提供任务编号。', actions: ['retry'] },
]

const DEFAULT_KIND = { kind: 'other', title: '任务失败', hint: '稍后点「重新开始」重试；反复失败请联系管理员。', actions: ['retry'] }

export const classifyProblem = (text) => KINDS.find((entry) => entry.test.test(String(text || ''))) || DEFAULT_KIND

const sortActions = (actions) => ACTION_ORDER.filter((action) => actions.includes(action))

// Problems from the structured `failures` list (new backend) or, failing that,
// from error/warning log lines (current backend). Also returns the chapters
// that are being retried right now so a retry is never silent.
export function collectIssues(taskStatus, logs = []) {
  const fromLogs = []
  const retrying = new Map()
  const skipped = new Set()
  let course = ''

  for (const entry of Array.isArray(logs) ? logs : []) {
    const text = String(entry?.message || '').trim()
    const started = text.match(/^Start course:\s*(.*)$/i) || text.match(/^开始学习课程：(.*)$/)
    if (started) {
      course = started[1].trim()
      continue
    }
    const chapterLog = parseChapterLog(text)
    const key = `${course}|${chapterLog?.chapter || ''}`
    if (chapterLog?.kind === 'retrying') {
      retrying.set(key, { course, chapter: chapterLog.chapter, reason: chapterLog.reason, tries: chapterLog.tries, timestamp: entry.timestamp })
      continue
    }
    if (chapterLog?.kind === 'skipped') {
      skipped.add(key)
      retrying.delete(key)
      fromLogs.push({ course, chapter: chapterLog.chapter, reason: chapterLog.reason, hint: chapterLog.hint, timestamp: entry.timestamp, chapterLevel: true })
      continue
    }
    if (entry?.level !== 'error' && entry?.level !== 'warning') continue
    // Whole-task summaries repeat what the headline already says.
    if (/^Task finished with failures|^Task cancelled by user$|^Task cancellation requested$/i.test(text)) continue
    if (/^Notification /i.test(text)) {
      fromLogs.push({ course: '', chapter: '', reason: translateTaskMessage(text), hint: '只影响完成通知，不影响刷课。可在「学习配置」检查通知设置。', timestamp: entry.timestamp, minor: true })
      continue
    }
    const finished = text.match(/^Course finished with (\d+) failed chapters?:\s*(.*)$/i)
    if (finished) {
      fromLogs.push({ course: finished[2].trim() || course, chapter: '', reason: `有 ${finished[1]} 个章节没有完成`, hint: '', timestamp: entry.timestamp, summary: true })
      continue
    }
    fromLogs.push({ course, chapter: '', reason: translateTaskMessage(text), hint: '', timestamp: entry.timestamp })
  }

  const failures = Array.isArray(taskStatus?.failures) ? taskStatus.failures : []
  let issues
  if (failures.length > 0) {
    const structured = failures.map((item) => ({
      course: normalizeCourseText(item?.course),
      chapter: normalizeCourseText(item?.chapter),
      reason: translateTaskMessage(item?.reason) || '原因未知',
      hint: normalizeCourseText(item?.hint),
      timestamp: item?.at || item?.timestamp || '',
    }))
    // Chapter lines and per-course summaries duplicate the structured list.
    issues = [...structured, ...fromLogs.filter((item) => !item.chapterLevel && !item.summary)]
  } else {
    const coursesWithChapters = new Set(fromLogs.filter((item) => item.chapterLevel).map((item) => item.course))
    issues = fromLogs.filter((item) => !(item.summary && coursesWithChapters.has(item.course)))
  }

  issues = issues.map((item) => {
    const kind = classifyProblem(`${item.reason} ${item.hint}`)
    return { ...item, hint: item.hint || kind.hint, actions: kind.actions }
  })

  return { issues, retrying: [...retrying.values()] }
}

const progressNumbers = (taskStatus) => {
  const progress = taskStatus?.progress || {}
  return {
    total: toNum(progress.total),
    completed: toNum(progress.completed),
    failed: toNum(progress.failed),
    totalChapters: toNum(progress.total_chapters),
    completedChapters: toNum(progress.completed_chapters),
    currentCourse: normalizeCourseText(progress.current_course),
    currentChapter: normalizeCourseText(progress.current_chapter),
  }
}

function failureAttention(taskStatus, issues, numbers) {
  const rawMessage = String(taskStatus?.message || '')
  const message = translateTaskMessage(rawMessage)
  const partial = /^Task finished with failures/i.test(rawMessage) || (numbers.failed > 0 && numbers.completed + numbers.failed >= numbers.total && numbers.total > 0)
  if (partial) {
    const failedCourses = numbers.failed || issues.filter((item) => item.summary).length || 1
    const actions = sortActions([...new Set(issues.flatMap((item) => item.actions || []).concat('retry'))]).slice(0, 3)
    return {
      tone: 'danger',
      title: `${failedCourses} 门课程没有全部完成`,
      summary: issues.length > 0 ? '下面是没完成的部分、原因和建议。' : `${message}。请查看下方日志里的「警告」和「错误」。`,
      issues,
      actions,
    }
  }
  const kind = classifyProblem(`${rawMessage} ${message}`)
  return {
    tone: 'danger',
    title: kind.title,
    summary: [message, kind.hint].filter(Boolean).join('。'),
    issues,
    actions: kind.actions,
  }
}

export function describeTask(taskStatus, logs = []) {
  const status = taskStatus ? normalizeStatus(taskStatus.status) || 'unknown' : 'idle'
  const numbers = progressNumbers(taskStatus)
  const message = translateTaskMessage(taskStatus?.message)
  const { issues, retrying } = collectIssues(taskStatus, logs)
  const active = ['pending', 'queued', 'started', 'starting', 'running', 'paused', 'cancelling', 'stopping'].includes(status)

  let headline = taskStatusLabel(status)
  let detail = message
  let attention = null

  if (status === 'idle') {
    headline = '还没有开始任务'
    detail = '选好课程后点「开始刷课」。'
  } else if (['pending', 'queued', 'started', 'starting'].includes(status)) {
    headline = '任务已创建，正在准备…'
  } else if (status === 'running') {
    if (taskStatus?.current_task === 'login') headline = '正在登录学习通…'
    else if (numbers.currentCourse) headline = `正在学习「${numbers.currentCourse}」`
    else headline = '正在学习…'
    detail = numbers.currentChapter ? `当前章节：${numbers.currentChapter}` : message
  } else if (status === 'paused') {
    headline = '任务已暂停'
    detail = '点「继续」从暂停的地方接着学。'
  } else if (status === 'cancelling' || status === 'stopping') {
    headline = '正在停止…'
    detail = '当前章节处理完就会停止。'
  } else if (status === 'completed') {
    headline = '全部完成'
    detail = numbers.total > 0 ? `${numbers.completed}/${numbers.total} 门课程已学完。` : message
  } else if (status === 'failed' || status === 'error') {
    attention = failureAttention(taskStatus, issues, numbers)
    headline = attention.title
    detail = numbers.total > 0 ? `已完成 ${numbers.completed}/${numbers.total} 门课程` : ''
  } else if (status === 'cancelled') {
    headline = '任务已取消'
  }

  if (active && (issues.length > 0 || retrying.length > 0)) {
    const notDone = issues.filter((item) => !item.minor)
    attention = {
      tone: 'warning',
      title: notDone.length > 0 ? `已有 ${notDone.length} 处没有完成` : `${retrying.length} 个章节正在自动重试`,
      summary: notDone.length > 0
        ? '任务会继续学习其他章节；结束后可按建议调整再重新开始。'
        : '第一次处理失败，系统会自动重试；重试后仍失败的会列在这里。',
      issues: [
        ...issues,
        ...retrying.map((item) => ({ ...item, hint: `正在自动重试（最多 ${item.tries} 次）…`, retrying: true })),
      ],
      actions: [],
    }
  } else if (status === 'completed' && issues.length > 0) {
    attention = { tone: 'warning', title: '任务完成，但有提醒', summary: '学习已完成，下面的问题不影响结果。', issues, actions: [] }
  }

  return { status, label: taskStatusLabel(status), tone: taskStatusTone(status), headline, detail, issues, retrying, attention, active }
}

// Errors from POST /course/start (or local checks before it).
export function describeStartError(err) {
  // ApiError carries a numeric status (0 = network/timeout); other errors don't.
  const status = typeof err?.status === 'number' ? err.status : null
  const raw = String(err?.message || '')
  const text = translateTaskMessage(raw)
  if (/answer-provider endpoint/i.test(raw) || text === '题库 / AI 答题服务地址不可用') {
    return {
      title: '题库设置需要调整',
      detail: '「AI 智能答题」和「题库适配器」需要一个公网可访问的服务地址，网页里还不能填写。请在「学习配置 › 答题与题库设置」里取消这两项，或换成其他题库后再开始。',
      actions: ['settings'],
    }
  }
  if (status === 409 || /active task already exists/i.test(raw)) {
    return { title: '这个账号已经有任务在运行', detail: '同一个账号一次只能运行一个任务。先查看或停止它，再开始新任务。', actions: ['tasks'] }
  }
  if (status === 429 || /capacity reached/i.test(raw)) {
    return { title: '服务器任务已满', detail: '现在同时运行的任务太多，请过几分钟再试。', actions: ['retry'] }
  }
  if (status === 401 || /请先登录学习通|登录已失效/.test(text)) {
    return { title: '学习通登录已失效', detail: `${text || '请重新登录学习通。'}`, actions: ['relogin'] }
  }
  if (status === 422) return { title: '提交的设置有误', detail: text, actions: ['settings'] }
  if (status === 0) return { title: '没能连上服务器', detail: text || '请检查网络后重试。', actions: ['retry'] }
  if (status !== null && status >= 500) return { title: '服务器暂时没能启动任务', detail: text, actions: ['retry'] }
  return { title: '没能开始刷课', detail: text || '启动任务失败，请稍后重试。', actions: ['retry'] }
}

// Course list / chapter list failures.
export function describeLoadError(err, subject) {
  const status = Number(err?.status) || 0
  const text = translateTaskMessage(err?.message) || `${subject}加载失败。`
  return { title: `${subject}没有加载出来`, detail: text, relogin: status === 401 || /请先登录|登录已失效|未登录/.test(text) }
}
