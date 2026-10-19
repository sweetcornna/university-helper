import { RefreshCw } from 'lucide-react'
import { Button, Input } from '../../../components'
import { chatActivityTypeLabel } from '../chatSignin'

export default function ChatSigninSection({ chat, hasCredentials, busy = false, onOpenAccount, locationFields }) {
  return (
    <section className="space-y-4" aria-label="群聊签到">
      <p className="text-sm text-text-muted">支持普通签到和位置签到，其他类型请在学习通中完成。</p>
      <form onSubmit={chat.submit} className="space-y-4">
        <div className="space-y-3">
          <Input id="cx-chat-link" label="活动链接（可选）" value={chat.form.activityLink} disabled={chat.submitting || busy} onChange={(event) => chat.updateForm('activityLink', event.target.value)} placeholder="粘贴学习通官方活动链接" />
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" variant="secondary" size="sm" disabled={chat.submitting || busy || !chat.form.activityLink.trim()} onClick={chat.applyLink}>解析活动链接</Button>
            <p className="min-w-0 text-xs text-text-muted">链接缺少群聊 ID 时请手动填写。</p>
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Input id="cx-chat-id" label="群聊 ID" value={chat.form.chatId} disabled={chat.submitting || busy} onChange={(event) => chat.updateForm('chatId', event.target.value)} placeholder="输入群聊 ID" />
          <Input id="cx-chat-active-id" label="活动 ID" value={chat.form.activeId} disabled={chat.submitting || busy} onChange={(event) => chat.updateForm('activeId', event.target.value)} placeholder="输入签到活动 ID" />
        </div>
        {chat.needsLocation && (
          <fieldset className="space-y-3 rounded-xl border border-border p-4">
            <legend className="px-1 text-sm font-semibold text-text">签到位置</legend>
            <p className="text-xs text-text-muted">老师看到的就是这里提交的位置，请选在上课地点附近。</p>
            {locationFields}
          </fieldset>
        )}
        {chat.error && <p role="alert" className="rounded-xl bg-danger-surface p-3 text-sm text-danger">{chat.error}</p>}
        {chat.notice && <p role="status" className="rounded-xl bg-primary/10 p-3 text-sm text-text">{chat.notice}</p>}
        <div className="flex flex-wrap gap-3">
          <Button type="submit" disabled={!hasCredentials || busy || chat.submitting || chat.unsupported || (!chat.form.activityLink.trim() && (!chat.form.chatId.trim() || !chat.form.activeId.trim()))}>{chat.submitting ? '签到中...' : '提交群聊签到'}</Button>
          <Button type="button" variant="secondary" disabled={chat.loading || chat.submitting || busy} onClick={chat.refresh}>
            <RefreshCw className={`mr-2 h-4 w-4 ${chat.loading ? 'animate-spin' : ''}`} aria-hidden="true" />{chat.loading ? '检测中...' : '检测群聊活动'}
          </Button>
        </div>
        {!hasCredentials && (
          <p className="text-sm text-text-muted">
            请先在
            <button type="button" className="mx-1 font-semibold text-primary hover:underline" onClick={onOpenAccount}>账号</button>
            中填写密码。
          </p>
        )}
      </form>
      <div className="space-y-3">
        {chat.warnings.length > 0 && <div role="status" className="rounded-xl bg-warning-surface p-4 text-sm text-text-muted"><p className="font-semibold text-text">检测范围提示</p><ul className="mt-2 list-disc space-y-1 pl-5">{chat.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
        {chat.detected && chat.activities.length === 0 && !chat.error && <p role="status" className="rounded-xl border border-dashed border-border p-4 text-sm text-text-muted">未检测到群聊活动。可确认群聊 ID 后重试，或填入老师发出的活动链接。</p>}
        {chat.activities.map((activity) => (
          <div key={`${activity.chatId}-${activity.activeId}`} className="flex flex-col justify-between gap-3 rounded-xl border border-border p-4 sm:flex-row sm:items-center">
            <div className="min-w-0">
              <h3 className="break-words font-semibold text-text">{activity.name || '群聊签到活动'}</h3>
              <p className="mt-1 text-sm text-text-muted">
                {chatActivityTypeLabel(activity.type)}
                {activity.type !== 'normal' && activity.type !== 'location' ? ' · 暂不支持，请在学习通中完成' : activity.status === 'active' ? ' · 进行中' : ' · 群里最近一条签到消息，是否已结束以提交结果为准'}
              </p>
              <p className="mt-1 break-all text-xs text-text-muted">群聊：{activity.chatId || chat.form.chatId || '未提供'} · 活动：{activity.activeId}</p>
            </div>
            <Button type="button" variant="secondary" disabled={chat.submitting || busy} onClick={() => chat.selectActivity(activity)}>选择此活动</Button>
          </div>
        ))}
      </div>
    </section>
  )
}
