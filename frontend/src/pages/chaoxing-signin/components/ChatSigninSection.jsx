import { Link2, RefreshCw, Search } from 'lucide-react'
import { Button, Input, StateNotice } from '../../../components'
import { chatActivityTypeLabel } from '../chatSignin'

export default function ChatSigninSection({ chat, hasCredentials, busy = false, onOpenAccount, locationFields }) {
  const hasResults = chat.warnings.length > 0 || chat.activities.length > 0 || (chat.detected && !chat.error)
  return (
    <section className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" aria-label="群聊签到">
      <div className="min-w-0 space-y-4">
        <p className="text-sm text-text-muted">支持普通签到和位置签到，其他类型请在学习通中完成。</p>
        <form onSubmit={chat.submit} className="space-y-4">
          <div className="space-y-2">
            <Input id="cx-chat-link" label="活动链接（可选）" value={chat.form.activityLink} disabled={chat.submitting || busy} onChange={(event) => chat.updateForm('activityLink', event.target.value)} placeholder="粘贴学习通官方活动链接" />
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" variant="secondary" size="sm" disabled={chat.submitting || busy || !chat.form.activityLink.trim()} onClick={chat.applyLink}>
                <Link2 className="h-3.5 w-3.5" aria-hidden="true" />
                解析活动链接
              </Button>
              <p className="min-w-0 text-xs text-text-muted">仅本地解析，不会打开链接。</p>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Input id="cx-chat-id" label="群聊 ID" value={chat.form.chatId} disabled={chat.submitting || busy} onChange={(event) => chat.updateForm('chatId', event.target.value)} placeholder="输入群聊 ID" inputMode="numeric" />
            <Input id="cx-chat-active-id" label="活动 ID" value={chat.form.activeId} disabled={chat.submitting || busy} onChange={(event) => chat.updateForm('activeId', event.target.value)} placeholder="输入签到活动 ID" inputMode="numeric" />
          </div>
          {chat.needsLocation && (
            <fieldset className="ui-panel space-y-3 p-4">
              <legend className="px-1 text-sm font-semibold text-text">签到位置</legend>
              {locationFields}
            </fieldset>
          )}
          {chat.error && <p role="alert" className="rounded-lg border border-danger/35 bg-danger-surface px-3 py-2.5 text-sm text-danger">{chat.error}</p>}
          {chat.notice && <p role="status" className="rounded-lg border border-primary/30 bg-primary/5 px-3 py-2.5 text-sm text-text">{chat.notice}</p>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={!hasCredentials || busy || chat.submitting || chat.unsupported || (!chat.form.activityLink.trim() && (!chat.form.chatId.trim() || !chat.form.activeId.trim()))}>{chat.submitting ? '签到中...' : '提交群聊签到'}</Button>
            <Button type="button" variant="secondary" disabled={chat.loading || chat.submitting || busy} onClick={chat.refresh}>
              <RefreshCw className={`h-4 w-4 ${chat.loading ? 'motion-safe:animate-spin' : ''}`} aria-hidden="true" />{chat.loading ? '检测中...' : '检测群聊活动'}
            </Button>
          </div>
          {chat.unsupported && chat.blockedReason !== chat.notice && chat.blockedReason !== chat.error && (
            <p className="text-xs text-warning">{chat.blockedReason}</p>
          )}
          {!hasCredentials && (
            <p className="text-sm text-text-muted">
              请先在
              <button type="button" className="mx-1 font-semibold text-primary underline-offset-4 hover:underline" onClick={onOpenAccount}>账号</button>
              中填写密码。
            </p>
          )}
        </form>
      </div>

      <div className="min-w-0 space-y-3">
        <p className="catalog-label">检测结果</p>
        {!hasResults && !chat.loading && (
          <StateNotice kind="empty" icon={Search} compact>
            填写群聊 ID 后检测。
          </StateNotice>
        )}
        {chat.loading && <StateNotice kind="loading" compact>正在检测群聊活动…</StateNotice>}
        {chat.warnings.length > 0 && <div role="status" className="rounded-lg border border-warning/35 bg-warning-surface p-3.5 text-sm text-text-muted"><p className="font-semibold text-text">检测范围提示</p><ul className="mt-2 list-disc space-y-1 pl-5">{chat.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
        {chat.detected && chat.activities.length === 0 && !chat.error && <p role="status" className="rounded-lg border border-dashed border-border bg-surface p-4 text-sm text-text-muted">未检测到群聊活动。</p>}
        {chat.activities.length > 0 && (
          <ul className="space-y-2">
            {chat.activities.map((activity) => {
              const selected = activity.activeId === chat.form.activeId.trim()
              const unsupportedType = activity.type !== 'normal' && activity.type !== 'location'
              const blocked = chat.isActivityBlocked(activity)
              return (
                <li key={`${activity.chatId}-${activity.activeId}`} className={`flex flex-col justify-between gap-3 rounded-lg border p-3.5 sm:flex-row sm:items-center ${selected ? 'border-primary/50 bg-primary/5' : 'border-border-subtle bg-surface'}`}>
                  <div className="min-w-0">
                    <h3 className="break-words text-sm font-semibold text-text">{activity.name || '群聊签到活动'}</h3>
                    <p className="mt-1 text-sm text-text-muted">
                      {chatActivityTypeLabel(activity.type)}
                      {unsupportedType ? ' · 暂不支持，请在学习通中完成' : blocked ? ' · 需在学习通完成' : activity.status === 'active' ? ' · 进行中' : ' · 状态未知'}
                    </p>
                    {activity.unsupportedReason && <p className="mt-1 text-xs text-warning">{activity.unsupportedReason}</p>}
                    <p className="font-code mt-1 break-all text-xs text-text-muted">群聊：{activity.chatId || chat.form.chatId || '未提供'} · 活动：{activity.activeId}</p>
                  </div>
                  <Button type="button" variant={selected ? 'primary' : 'secondary'} size="sm" disabled={chat.submitting || busy} onClick={() => chat.selectActivity(activity)}>选择此活动</Button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </section>
  )
}
