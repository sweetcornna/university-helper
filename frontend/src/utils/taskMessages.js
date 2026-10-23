// Translates the English task/status/log messages the backend writes into the
// Chinese the UI shows. Chinese or unrecognised text passes through untouched,
// so new backend wording never disappears, it just is not reworded.

const detailSuffix = (detail) => {
  const text = String(detail || '').trim()
  return text ? `（${text}）` : ''
}

// Ordered: the first matching rule wins. Each rule receives the regex match.
const RULES = [
  // Chaoxing learning worker (learning_manager.py)
  [/^Task created$/i, () => '任务已创建'],
  [/^Course learning task started$/i, () => '任务已创建，正在准备'],
  [/^Logging in to Chaoxing$/i, () => '正在登录学习通'],
  [/^Starting login\.*$/i, () => '开始登录学习通…'],
  [/^Login successful$/i, () => '学习通登录成功'],
  [/^Login failed$/i, () => '学习通登录失败'],
  [/^Login request failed:\s*(.*)$/i, (m) => `学习通登录请求失败${detailSuffix(m[1])}`],
  [/^Initialize chaoxing client failed:\s*(.*)$/i, (m) => `初始化学习通连接失败${detailSuffix(m[1])}`],
  [/^Fetch course list failed:\s*(.*)$/i, (m) => `获取学习通课程列表失败${detailSuffix(m[1])}`],
  [/^No available courses after filtering$/i, () => '所选课程在学习通里都找不到了'],
  [/^Selected (\d+) courses?, speed ([\d.]+)x, jobs (\d+)$/i, (m) => `已选 ${m[1]} 门课程，${m[2]} 倍速，${m[3]} 个并发章节`],
  [/^Learning course (\d+)\/(\d+)$/i, (m) => `正在学习第 ${m[1]}/${m[2]} 门课程`],
  [/^Start course:\s*(.*)$/i, (m) => `开始学习课程：${m[1]}`],
  [/^Fetch chapters failed for (.+?):\s*(.*)$/i, (m) => `获取「${m[1]}」的章节失败${detailSuffix(m[2])}`],
  [/^Chosen last chapter no longer exists in (.+?); course skipped\..*$/i, (m) => `「${m[1]}」里找不到你选的最后一节，这门课已跳过。请刷新章节列表后重新选择。`],
  [/^Studying (.+?) up to "(.*)" \((\d+)\/(\d+) chapters\)$/i, (m) => `「${m[1]}」只学到「${m[2]}」（${m[3]}/${m[4]} 节）`],
  [/^Course finished with (\d+) failed chapters?:\s*(.*)$/i, (m) => `课程结束，有 ${m[1]} 个章节没有完成：${m[2]}`],
  [/^Course completed:\s*(.*)$/i, (m) => `课程完成：${m[1]}`],
  [/^Course execution failed (.+?):\s*(.*)$/i, (m) => `课程「${m[1]}」执行出错${detailSuffix(m[2])}`],
  [/^Task finished with failures \((\d+) failed courses?\)$/i, (m) => `任务结束，${m[1]} 门课程没有全部完成`],
  [/^Task finished with failures$/i, () => '任务结束，有课程没有全部完成'],
  [/^Task completed$/i, () => '任务完成'],
  [/^Task paused$/i, () => '任务已暂停'],
  [/^Task resumed$/i, () => '任务已继续'],
  [/^Task cancellation requested$/i, () => '已请求停止，当前章节结束后停止'],
  [/^Task cancelled by user$/i, () => '任务已按你的要求停止'],
  [/^Task cancelled$/i, () => '任务已取消'],
  [/^Task interrupted due to service restart$/i, () => '服务重启，任务被中断'],
  [/^Unexpected task failure:\s*(.*)$/i, (m) => `任务意外出错${detailSuffix(m[1])}`],
  [/^Server cannot start a new background thread\b.*$/i, () => '服务器暂时无法启动新任务。请先停止其他任务后重试，仍不行请联系管理员。'],
  [/^Failed to persist learning task state$/i, () => '服务器没能保存任务状态'],
  [/^Task is running$/i, () => '任务进行中'],
  [/^Notification skipped: unsupported service$/i, () => '未发送完成通知：不支持这个通知服务'],
  [/^Notification skipped: URL validation failed$/i, () => '未发送完成通知：通知地址校验失败'],
  [/^Notification skipped: URL must be a public http\(s\) address$/i, () => '未发送完成通知：通知地址必须是公网 http(s) 地址'],
  [/^Notification sent via (.+)$/i, (m) => `已通过 ${m[1]} 发送完成通知`],
  [/^Notification failed \((.+)\)$/i, (m) => `完成通知发送失败（${m[1]}）`],
  // API errors that reach the page
  [/^Invalid answer-provider endpoint configuration$/i, () => '题库 / AI 答题服务地址不可用'],
  [/^An active task already exists for this user$/i, () => '这个账号已经有任务在运行'],
  [/^Task capacity reached; retry later$/i, () => '服务器任务已满，请稍后再试'],
  [/^Task not found$/i, () => '找不到这个任务'],
  [/^Please login to Chaoxing first$/i, () => '请先登录学习通'],
  [/^Failed to start course learning task$/i, () => '服务器没能启动刷课任务'],
  [/^Failed to load Chaoxing chapters$/i, () => '获取学习通章节失败'],
  [/^Failed to login and load Chaoxing courses$/i, () => '登录学习通并获取课程失败'],
  [/^Only chaoxing is supported$/i, () => '目前只支持学习通'],
  // Zhihuishu adapter / routes
  [/^Zhihuishu not logged in$/i, () => '智慧树未登录或登录已失效'],
  [/^Zhihuishu login failed$/i, () => '智慧树登录失败'],
  [/^Failed to load Zhihuishu videos$/i, () => '读取智慧树视频列表失败'],
  [/^Failed to load (?:grouped )?Zhihuishu courses$/i, () => '读取智慧树课程失败'],
  [/^Failed to load Zhihuishu (progress|status|task|tasks|config)$/i, () => '读取智慧树数据失败'],
  [/^Failed to start Zhihuishu (?:AI course |course )?task$/i, () => '没能启动智慧树任务'],
  [/^Failed to load course detail$/i, () => '读取课程详情失败'],
  [/^Task started$/i, () => '任务已启动'],
  [/^AI course task started$/i, () => 'AI 课程任务已启动'],
  [/^Task already (finished|completed)$/i, () => '任务已经结束'],
  [/^Task already cancelled$/i, () => '任务已经取消'],
  [/^No running task$/i, () => '当前没有进行中的任务'],
  [/^Waiting for scan$/i, () => '等待扫码'],
  [/^Logout successful$/i, () => '已退出'],
]

export const translateTaskMessage = (value) => {
  const text = String(value ?? '').trim()
  if (!text) return ''
  for (const [pattern, render] of RULES) {
    const match = text.match(pattern)
    if (match) return render(match)
  }
  return text
}

// `current_task` is a machine value such as "login" or "chapter:1.2 xx".
export const translateCurrentTask = (value) => {
  const text = String(value ?? '').trim()
  if (!text) return ''
  const simple = { preparing: '准备中', login: '登录学习通', paused: '已暂停', cancelled: '已取消', failed: '已结束（失败）', finished: '已结束' }
  if (simple[text]) return simple[text]
  const scoped = text.match(/^(course|chapter):(.*)$/)
  if (scoped) return `${scoped[1] === 'course' ? '课程' : '章节'}：${scoped[2]}`
  return translateTaskMessage(text)
}
