'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { API_BASE } from '@/lib/constants'
import type { ChannelsMap, GuildsMap, MessageMilestoneConfig } from '@/lib/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { DataTable, type Column } from '@/components/data-table'
import { DeleteButton } from '@/components/delete-button'
import { GuildChannelSelector } from '@/components/guild-channel-selector'
import { ToggleButton } from '@/components/toggle-button'

type ConditionType = 'daily_streak' | 'consecutive_posts'
type ConsecutiveNotificationLimit = 'none' | 'per_user_per_day'

const CONDITION_LABELS: Record<ConditionType, string> = {
  consecutive_posts: 'N回連続投稿',
  daily_streak: '1日N回 x N日',
}

const DEFAULT_PLAIN_MESSAGES: Record<ConditionType, string> = {
  consecutive_posts: '{username} さん、連続 {current_count} 回目です！',
  daily_streak: '{username} さん、{current_count}日コンボ！ 1日 {n} 回達成です！',
}

const DEFAULT_EMBED_TITLES: Record<ConditionType, string> = {
  consecutive_posts: '{username} さん、連続記録更新！',
  daily_streak: '{username} さん、投稿習慣達成！',
}

const DEFAULT_EMBED_DESCRIPTIONS: Record<ConditionType, string> = {
  consecutive_posts: 'いま連続 {current_count} 回目です。',
  daily_streak: '1日 {n} 回の投稿を{current_count}日連続で達成しました。',
}

function conditionHelp(conditionType: ConditionType) {
  return conditionType === 'consecutive_posts'
    ? '同じユーザーの対象投稿がN回続いたら通知を始めます。通知頻度で、毎回通知するか1日N回までに抑えるかを選べます。別ユーザーの対象投稿が入るとリセットします。'
    : '同じユーザーが1日N回以上の投稿を達成した日ごとに通知します。{current_count} で現在のコンボ日数を表示できます。'
}

function conditionSummary(row: MessageMilestoneConfig) {
  if (row.condition_type === 'consecutive_posts') {
    const limit =
      row.consecutive_notification_limit === 'per_user_per_day'
        ? `1日${row.consecutive_notification_daily_limit ?? 1}回まで`
        : '毎回通知'
    return `${row.daily_required_count}回目から / ${limit}`
  }
  return `1日${row.daily_required_count}回 x ${row.required_days}日`
}

function conditionTypeLabel(conditionType: ConditionType) {
  return CONDITION_LABELS[conditionType]
}

function renderTemplate(template: string, n: string, currentCount: string) {
  return template
    .replaceAll('{username}', 'いつか')
    .replaceAll('{n}', n)
    .replaceAll('{count}', n)
    .replaceAll('{current_count}', currentCount)
    .replaceAll('{current}', currentCount)
}

function resolveGuildName(guilds: GuildsMap, guildId: string) {
  return guilds[guildId] ?? guildId
}

function resolveChannelName(channels: ChannelsMap, guildId: string, channelId: string) {
  const list = channels[guildId] ?? []
  const ch = list.find((c) => c.id === channelId)
  return ch ? `#${ch.name}` : channelId
}

interface MessageMilestoneListResponse {
  configs: MessageMilestoneConfig[]
  guilds: GuildsMap
  channels: ChannelsMap
}

export default function MessageMilestonePage() {
  const router = useRouter()
  const [configs, setConfigs] = useState<MessageMilestoneConfig[]>([])
  const [guilds, setGuilds] = useState<GuildsMap>({})
  const [channels, setChannels] = useState<ChannelsMap>({})
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [selectedGuild, setSelectedGuild] = useState('')
  const [selectedChannel, setSelectedChannel] = useState('')
  const [conditionType, setConditionType] = useState<ConditionType>('consecutive_posts')
  const [consecutiveNotificationLimit, setConsecutiveNotificationLimit] =
    useState<ConsecutiveNotificationLimit>('per_user_per_day')
  const [consecutiveNotificationDailyLimit, setConsecutiveNotificationDailyLimit] = useState('1')
  const [dailyRequiredCount, setDailyRequiredCount] = useState('1')
  const [requiredDays, setRequiredDays] = useState('1')
  const [pattern, setPattern] = useState('')
  const [patternProbe, setPatternProbe] = useState('てすと')
  const [responseType, setResponseType] = useState<'plain' | 'embed'>('plain')
  const [messageContent, setMessageContent] = useState(DEFAULT_PLAIN_MESSAGES.consecutive_posts)
  const [embedTitle, setEmbedTitle] = useState(DEFAULT_EMBED_TITLES.consecutive_posts)
  const [embedDescription, setEmbedDescription] = useState(
    DEFAULT_EMBED_DESCRIPTIONS.consecutive_posts
  )
  const [embedColor, setEmbedColor] = useState('#22C55E')
  const [deleteAfterSeconds, setDeleteAfterSeconds] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const formRef = useRef<HTMLDivElement | null>(null)

  const selectedTarget = useMemo(
    () =>
      selectedGuild && selectedChannel
        ? `${resolveGuildName(guilds, selectedGuild)} / ${resolveChannelName(
            channels,
            selectedGuild,
            selectedChannel
          )}`
        : '',
    [channels, guilds, selectedChannel, selectedGuild]
  )
  const patternPreview = useMemo(() => {
    const trimmedPattern = pattern.trim()
    if (!trimmedPattern) {
      return { kind: 'empty' as const, label: 'フィルタなし' }
    }
    try {
      return new RegExp(trimmedPattern).test(patternProbe)
        ? { kind: 'match' as const, label: 'マッチします' }
        : { kind: 'miss' as const, label: 'マッチしません' }
    } catch {
      return { kind: 'error' as const, label: '正規表現エラー' }
    }
  }, [pattern, patternProbe])
  const messagePreview = useMemo(() => {
    const threshold = dailyRequiredCount.trim() || 'N'
    const currentCount =
      conditionType === 'consecutive_posts'
        ? Number.isFinite(Number(dailyRequiredCount))
          ? String(Math.max(Number(dailyRequiredCount), 1))
          : threshold
        : requiredDays.trim() || 'N'

    return {
      content: messageContent.trim() ? renderTemplate(messageContent, threshold, currentCount) : '',
      embedTitle: embedTitle.trim() ? renderTemplate(embedTitle, threshold, currentCount) : '',
      embedDescription: embedDescription.trim()
        ? renderTemplate(embedDescription, threshold, currentCount)
        : '',
    }
  }, [conditionType, dailyRequiredCount, embedDescription, embedTitle, messageContent, requiredDays])
  const formSummary = useMemo(() => {
    const count = dailyRequiredCount.trim() || 'N'
    if (conditionType === 'consecutive_posts') {
      const limit =
        consecutiveNotificationLimit === 'per_user_per_day'
          ? `ユーザーごとに1日${consecutiveNotificationDailyLimit.trim() || 'N'}回まで`
          : '連続投稿ごとに毎回'
      return `${count}回目から連続達成を通知 / ${limit}`
    }
    return `1日${count}回達成ごとに通知 / 目標 ${requiredDays.trim() || 'N'}日コンボ`
  }, [
    conditionType,
    consecutiveNotificationDailyLimit,
    consecutiveNotificationLimit,
    dailyRequiredCount,
    requiredDays,
  ])

  async function fetchData() {
    const res = await fetch(`${API_BASE}/message-milestone`)
    if (res.status === 401) {
      router.push('/login')
      return
    }
    const body = (await res.json()) as Partial<MessageMilestoneListResponse>
    setConfigs(body.configs ?? [])
    setGuilds(body.guilds ?? {})
    setChannels(body.channels ?? {})
    setLoading(false)
  }

  useEffect(() => {
    fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function resetForm() {
    setEditingId(null)
    setSelectedGuild('')
    setSelectedChannel('')
    setConditionType('consecutive_posts')
    setConsecutiveNotificationLimit('per_user_per_day')
    setConsecutiveNotificationDailyLimit('1')
    setDailyRequiredCount('1')
    setRequiredDays('1')
    setPattern('')
    setPatternProbe('てすと')
    setResponseType('plain')
    setMessageContent(DEFAULT_PLAIN_MESSAGES.consecutive_posts)
    setEmbedTitle(DEFAULT_EMBED_TITLES.consecutive_posts)
    setEmbedDescription(DEFAULT_EMBED_DESCRIPTIONS.consecutive_posts)
    setEmbedColor('#22C55E')
    setDeleteAfterSeconds('')
    setError('')
  }

  function startEdit(row: MessageMilestoneConfig) {
    setEditingId(row.id)
    setSelectedGuild(row.guild_id)
    setSelectedChannel(row.channel_id)
    setConditionType(row.condition_type)
    setConsecutiveNotificationLimit(row.consecutive_notification_limit ?? 'none')
    setConsecutiveNotificationDailyLimit(String(row.consecutive_notification_daily_limit ?? 1))
    setDailyRequiredCount(String(row.daily_required_count))
    setRequiredDays(String(row.required_days))
    setPattern(row.pattern ?? '')
    setResponseType(row.response_type)
    setMessageContent(row.message_content ?? '')
    setEmbedTitle(row.embed_title ?? '')
    setEmbedDescription(row.embed_description ?? '')
    setEmbedColor(row.embed_color ?? '#22C55E')
    setDeleteAfterSeconds(row.delete_after_seconds ? String(row.delete_after_seconds) : '')
    setError('')
    formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function handleConditionTypeChange(next: ConditionType) {
    setConditionType(next)
    const defaultPlainValues = Object.values(DEFAULT_PLAIN_MESSAGES)
    const defaultEmbedTitles = Object.values(DEFAULT_EMBED_TITLES)
    const defaultEmbedDescriptions = Object.values(DEFAULT_EMBED_DESCRIPTIONS)

    if (!messageContent.trim() || defaultPlainValues.includes(messageContent)) {
      setMessageContent(DEFAULT_PLAIN_MESSAGES[next])
    }
    if (!embedTitle.trim() || defaultEmbedTitles.includes(embedTitle)) {
      setEmbedTitle(DEFAULT_EMBED_TITLES[next])
    }
    if (!embedDescription.trim() || defaultEmbedDescriptions.includes(embedDescription)) {
      setEmbedDescription(DEFAULT_EMBED_DESCRIPTIONS[next])
    }
  }

  function handleResponseTypeChange(next: 'plain' | 'embed') {
    setResponseType(next)
    if (next === 'plain' && !messageContent.trim()) {
      setMessageContent(DEFAULT_PLAIN_MESSAGES[conditionType])
    }
    if (next === 'embed') {
      if (!embedTitle.trim()) setEmbedTitle(DEFAULT_EMBED_TITLES[conditionType])
      if (!embedDescription.trim()) {
        setEmbedDescription(DEFAULT_EMBED_DESCRIPTIONS[conditionType])
      }
    }
  }

  async function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault()
    setError('')
    if (!selectedGuild || !selectedChannel) return
    const daily = Number(dailyRequiredCount)
    const days = Number(requiredDays)
    if (!Number.isInteger(daily) || !Number.isInteger(days)) {
      setError('投稿数と日数は整数で入力してください')
      return
    }
    if (daily < 1 || daily > 999) {
      setError('投稿数は 1〜999 で入力してください')
      return
    }
    if (conditionType === 'daily_streak' && (days < 1 || days > 365)) {
      setError('継続日数は 1〜365 で入力してください')
      return
    }
    const notificationDailyLimit = Number(consecutiveNotificationDailyLimit)
    if (
      conditionType === 'consecutive_posts' &&
      consecutiveNotificationLimit === 'per_user_per_day' &&
      (!Number.isInteger(notificationDailyLimit) ||
        notificationDailyLimit < 1 ||
        notificationDailyLimit > 999)
    ) {
      setError('1日あたりの通知回数は 1〜999 で入力してください')
      return
    }
    const deleteAfter = deleteAfterSeconds.trim() ? Number(deleteAfterSeconds) : null
    if (deleteAfter !== null && !Number.isInteger(deleteAfter)) {
      setError('自動削除の秒数は整数で入力してください')
      return
    }
    if (deleteAfter !== null && (deleteAfter < 1 || deleteAfter > 300)) {
      setError('自動削除秒数は 1〜300 で入力してください')
      return
    }
    setSubmitting(true)
    try {
      const isEdit = editingId !== null
      const url = isEdit
        ? `${API_BASE}/message-milestone/${editingId}`
        : `${API_BASE}/message-milestone`
      const method = isEdit ? 'PATCH' : 'POST'
      const payload = {
        guild_id: selectedGuild,
        channel_id: selectedChannel,
        condition_type: conditionType,
        consecutive_notification_limit:
          conditionType === 'consecutive_posts' ? consecutiveNotificationLimit : 'none',
        consecutive_notification_daily_limit:
          conditionType === 'consecutive_posts' &&
          consecutiveNotificationLimit === 'per_user_per_day'
            ? notificationDailyLimit
            : 1,
        daily_required_count: daily,
        required_days: conditionType === 'daily_streak' ? days : 1,
        pattern: pattern.trim() || null,
        response_type: responseType,
        message_content: messageContent.trim() || null,
        embed_title: embedTitle.trim() || null,
        embed_description: embedDescription.trim() || null,
        embed_color: embedColor.trim() || null,
        delete_after_seconds: deleteAfter,
      }
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.detail || (isEdit ? '更新に失敗しました' : '追加に失敗しました'))
        return
      }
      resetForm()
      await fetchData()
      router.refresh()
    } finally {
      setSubmitting(false)
    }
  }

  const isEdit = editingId !== null
  const canSubmit =
    selectedGuild &&
    selectedChannel &&
    (responseType === 'plain'
      ? messageContent.trim()
      : embedTitle.trim() || embedDescription.trim())

  const columns: Column<MessageMilestoneConfig>[] = [
    {
      header: 'サーバー',
      accessor: (row) => resolveGuildName(guilds, row.guild_id),
    },
    {
      header: 'チャンネル',
      accessor: (row) => resolveChannelName(channels, row.guild_id, row.channel_id),
    },
    {
      header: '条件',
      accessor: (row) => (
        <div className="space-y-1 text-sm">
          <div className="font-medium">{conditionTypeLabel(row.condition_type)}</div>
          <div className="text-muted-foreground">{conditionSummary(row)}</div>
          {row.pattern ? <code className="text-xs">{row.pattern}</code> : null}
        </div>
      ),
    },
    {
      header: '削除',
      accessor: (row) => (row.delete_after_seconds ? `${row.delete_after_seconds}s` : '-'),
    },
    {
      header: 'メッセージ',
      accessor: (row) => (
        <div className="max-w-xs truncate text-sm">
          {row.response_type === 'embed' ? (
            <span>
              埋め込み: {row.embed_title || row.embed_description || row.message_content || '(空)'}
            </span>
          ) : (
            <span>{row.message_content}</span>
          )}
        </div>
      ),
    },
    {
      header: '状態',
      accessor: (row) => (
        <Badge
          variant={row.enabled ? 'default' : 'secondary'}
          className={row.enabled ? 'bg-green-600 hover:bg-green-600' : ''}
        >
          {row.enabled ? '有効' : '停止中'}
        </Badge>
      ),
    },
    {
      header: '操作',
      accessor: (row) => (
        <div className="flex items-center gap-2">
          <ToggleButton
            endpoint={`${API_BASE}/message-milestone/${row.id}/toggle`}
            enabled={row.enabled}
            onSuccess={fetchData}
          />
          <Button
            variant="outline"
            size="sm"
            onClick={() => startEdit(row)}
            disabled={editingId === row.id}
          >
            編集
          </Button>
          <DeleteButton
            endpoint={`${API_BASE}/message-milestone/${row.id}`}
            onSuccess={fetchData}
          />
        </div>
      ),
    },
  ]

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">投稿達成メッセージ</h1>
        <p className="text-muted-foreground">読み込み中...</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">投稿達成メッセージ</h1>

      <div ref={formRef}>
        <Card>
          <CardHeader>
            <CardTitle>{isEdit ? '設定を編集' : '設定を追加'}</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              {isEdit ? (
                <div className="rounded-md border border-input bg-muted/40 px-3 py-2 text-sm">
                  <span className="text-muted-foreground">対象: </span>
                  <span className="font-medium">{selectedTarget}</span>
                  <span className="ml-2 text-xs text-muted-foreground">
                    (サーバー / チャンネルは変更不可。変えたい場合は削除して再追加)
                  </span>
                </div>
              ) : (
                <GuildChannelSelector
                  guilds={guilds}
                  channels={channels}
                  selectedGuild={selectedGuild}
                  selectedChannel={selectedChannel}
                  onGuildChange={setSelectedGuild}
                  onChannelChange={setSelectedChannel}
                />
              )}

              <div>
                <label className="mb-1.5 block text-sm font-medium">達成条件</label>
                <Select
                  value={conditionType}
                  onValueChange={(v) => handleConditionTypeChange(v as ConditionType)}
                >
                  <SelectTrigger className="w-full md:w-80">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="consecutive_posts">
                      {CONDITION_LABELS.consecutive_posts}
                    </SelectItem>
                    <SelectItem value="daily_streak">{CONDITION_LABELS.daily_streak}</SelectItem>
                  </SelectContent>
                </Select>
                <p className="mt-1 text-xs text-muted-foreground">{conditionHelp(conditionType)}</p>
              </div>

              <div className="rounded-md border border-input bg-muted/20 px-3 py-2 text-sm">
                <span className="text-muted-foreground">現在の条件: </span>
                <span className="font-medium">{formSummary}</span>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <label
                    htmlFor="daily-required-count"
                    className="mb-1.5 block text-sm font-medium"
                  >
                    {conditionType === 'consecutive_posts'
                      ? '通知を始める連続回数'
                      : '1日あたりの投稿数'}
                  </label>
                  <Input
                    id="daily-required-count"
                    type="number"
                    min="1"
                    max="999"
                    value={dailyRequiredCount}
                    onChange={(e) => setDailyRequiredCount(e.target.value)}
                  />
                </div>
                {conditionType === 'daily_streak' && (
                  <div>
                    <label htmlFor="required-days" className="mb-1.5 block text-sm font-medium">
                      継続日数
                    </label>
                    <Input
                      id="required-days"
                      type="number"
                      min="1"
                      max="365"
                      value={requiredDays}
                      onChange={(e) => setRequiredDays(e.target.value)}
                    />
                  </div>
                )}
                {conditionType === 'consecutive_posts' && (
                  <div>
                    <label className="mb-1.5 block text-sm font-medium">通知頻度</label>
                    <Select
                      value={consecutiveNotificationLimit}
                      onValueChange={(v) =>
                        setConsecutiveNotificationLimit(v as ConsecutiveNotificationLimit)
                      }
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="per_user_per_day">ユーザーごとに1日N回まで</SelectItem>
                        <SelectItem value="none">連続投稿ごとに毎回</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </div>

              {conditionType === 'consecutive_posts' &&
                consecutiveNotificationLimit === 'per_user_per_day' && (
                  <div>
                    <label
                      htmlFor="consecutive-notification-daily-limit"
                      className="mb-1.5 block text-sm font-medium"
                    >
                      1日あたりの通知上限
                    </label>
                    <Input
                      id="consecutive-notification-daily-limit"
                      type="number"
                      min="1"
                      max="999"
                      value={consecutiveNotificationDailyLimit}
                      onChange={(e) => setConsecutiveNotificationDailyLimit(e.target.value)}
                    />
                    <p className="mt-1 text-xs text-muted-foreground">
                      ユーザーごとに、この回数まで連続達成通知を送ります。1 にすると1日1回です。
                    </p>
                  </div>
                )}

              <div>
                <label htmlFor="pattern" className="mb-1.5 block text-sm font-medium">
                  カウント対象フィルタ
                  <span className="text-muted-foreground"> (正規表現・任意)</span>
                </label>
                <Input
                  id="pattern"
                  type="text"
                  placeholder="例: (?i)参加|done|#daily"
                  value={pattern}
                  onChange={(e) => setPattern(e.target.value)}
                  spellCheck={false}
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  本文がこの正規表現にマッチした投稿だけをN回のカウント対象にします。
                  フィルタを使う場合は Bot の Message Content Intent が必要です。
                  連続投稿モードでは、フィルタ対象外の投稿は連続判定に含めません。
                </p>
                <div className="mt-2 grid gap-2 md:grid-cols-[1fr_auto]">
                  <Input
                    type="text"
                    value={patternProbe}
                    onChange={(e) => setPatternProbe(e.target.value)}
                    placeholder="この文字列でフィルタを確認"
                    spellCheck={false}
                    aria-label="フィルタ確認用テキスト"
                  />
                  <Badge
                    variant={patternPreview.kind === 'match' ? 'default' : 'secondary'}
                    className={
                      patternPreview.kind === 'match'
                        ? 'justify-center bg-green-600 hover:bg-green-600'
                        : patternPreview.kind === 'error'
                          ? 'justify-center bg-red-700 text-white hover:bg-red-700'
                          : 'justify-center'
                    }
                  >
                    {patternPreview.label}
                  </Badge>
                </div>
              </div>

              <div>
                <label htmlFor="delete-after-seconds" className="mb-1.5 block text-sm font-medium">
                  自動削除秒数 <span className="text-muted-foreground">(任意)</span>
                </label>
                <Input
                  id="delete-after-seconds"
                  type="number"
                  min="1"
                  max="300"
                  value={deleteAfterSeconds}
                  onChange={(e) => setDeleteAfterSeconds(e.target.value)}
                  placeholder="例: 30"
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  設定すると送信メッセージ内で秒数をカウントダウンし、0秒で削除します。
                </p>
              </div>

              <div>
                <label className="mb-1.5 block text-sm font-medium">送信形式</label>
                <Select
                  value={responseType}
                  onValueChange={(v) => handleResponseTypeChange(v as 'plain' | 'embed')}
                >
                  <SelectTrigger className="w-full md:w-64">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="plain">通常メッセージ</SelectItem>
                    <SelectItem value="embed">埋め込みメッセージ</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div>
                <label htmlFor="message-content" className="mb-1.5 block text-sm font-medium">
                  通常メッセージ本文
                  {responseType === 'embed' && (
                    <span className="text-muted-foreground"> (任意)</span>
                  )}
                </label>
                <textarea
                  id="message-content"
                  className="min-h-24 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                  value={messageContent}
                  onChange={(e) => setMessageContent(e.target.value)}
                  maxLength={2000}
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  テンプレート変数: <code>{'{username}'}</code> はユーザー名、
                  <code>{'{n}'}</code> は設定した投稿数、
                  <code>{'{current_count}'}</code> は現在の連続回数/コンボ日数です。
                </p>
              </div>

              {responseType === 'embed' && (
                <div className="space-y-4 rounded-md border border-input p-4">
                  <div className="grid gap-3 md:grid-cols-[1fr_10rem]">
                    <div>
                      <label htmlFor="embed-title" className="mb-1.5 block text-sm font-medium">
                        埋め込みタイトル
                      </label>
                      <Input
                        id="embed-title"
                        type="text"
                        placeholder="{username} さん、おめでとう"
                        value={embedTitle}
                        onChange={(e) => setEmbedTitle(e.target.value)}
                        maxLength={256}
                      />
                    </div>
                    <div>
                      <label htmlFor="embed-color" className="mb-1.5 block text-sm font-medium">
                        色
                      </label>
                      <Input
                        id="embed-color"
                        type="text"
                        value={embedColor}
                        onChange={(e) => setEmbedColor(e.target.value)}
                        placeholder="#22C55E"
                      />
                    </div>
                  </div>
                  <div>
                    <label htmlFor="embed-description" className="mb-1.5 block text-sm font-medium">
                      埋め込み説明
                    </label>
                    <textarea
                      id="embed-description"
                      className="min-h-32 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                      placeholder="{n} 回投稿を達成しました"
                      value={embedDescription}
                      onChange={(e) => setEmbedDescription(e.target.value)}
                      maxLength={4096}
                    />
                  </div>
                </div>
              )}

              <div className="rounded-md border border-input bg-muted/20 p-4">
                <div className="mb-2 text-sm font-medium">プレビュー</div>
                {responseType === 'embed' ? (
                  <div className="space-y-2">
                    {messagePreview.content && (
                      <div className="whitespace-pre-wrap text-sm">{messagePreview.content}</div>
                    )}
                    <div className="border-l-4 border-green-600 bg-background px-3 py-2">
                      <div className="text-sm font-semibold">
                        {messagePreview.embedTitle || '埋め込みタイトル'}
                      </div>
                      <div className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">
                        {messagePreview.embedDescription || '埋め込み説明'}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="whitespace-pre-wrap text-sm">
                    {messagePreview.content || '通常メッセージ本文'}
                  </div>
                )}
              </div>

              {error && <p className="text-sm text-destructive">{error}</p>}
              <div className="flex items-center gap-2">
                <Button type="submit" disabled={submitting || !canSubmit}>
                  {submitting ? (isEdit ? '保存中...' : '追加中...') : isEdit ? '保存' : '追加'}
                </Button>
                {isEdit && (
                  <Button type="button" variant="outline" onClick={resetForm} disabled={submitting}>
                    キャンセル
                  </Button>
                )}
              </div>
            </form>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>設定済みの投稿達成メッセージ</CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={columns}
            data={configs}
            emptyMessage="投稿達成メッセージはまだ設定されていません"
          />
        </CardContent>
      </Card>
    </div>
  )
}
