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
  const [dailyRequiredCount, setDailyRequiredCount] = useState('1')
  const [requiredDays, setRequiredDays] = useState('1')
  const [pattern, setPattern] = useState('')
  const [responseType, setResponseType] = useState<'plain' | 'embed'>('plain')
  const [messageContent, setMessageContent] = useState('')
  const [embedTitle, setEmbedTitle] = useState('')
  const [embedDescription, setEmbedDescription] = useState('')
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
    setDailyRequiredCount('1')
    setRequiredDays('1')
    setPattern('')
    setResponseType('plain')
    setMessageContent('')
    setEmbedTitle('')
    setEmbedDescription('')
    setEmbedColor('#22C55E')
    setDeleteAfterSeconds('')
    setError('')
  }

  function startEdit(row: MessageMilestoneConfig) {
    setEditingId(row.id)
    setSelectedGuild(row.guild_id)
    setSelectedChannel(row.channel_id)
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
    const deleteAfter = deleteAfterSeconds.trim() ? Number(deleteAfterSeconds) : null
    if (deleteAfter !== null && !Number.isInteger(deleteAfter)) {
      setError('自動削除の秒数は整数で入力してください')
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
        daily_required_count: daily,
        required_days: days,
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
      header: 'Server',
      accessor: (row) => resolveGuildName(guilds, row.guild_id),
    },
    {
      header: 'Channel',
      accessor: (row) => resolveChannelName(channels, row.guild_id, row.channel_id),
    },
    {
      header: 'Condition',
      accessor: (row) => (
        <div className="space-y-1 text-sm">
          <div>{`${row.daily_required_count} posts/day x ${row.required_days} days`}</div>
          {row.pattern ? <code className="text-xs">{row.pattern}</code> : null}
        </div>
      ),
    },
    {
      header: 'Delete',
      accessor: (row) => (row.delete_after_seconds ? `${row.delete_after_seconds}s` : '-'),
    },
    {
      header: 'Message',
      accessor: (row) => (
        <div className="max-w-xs truncate text-sm">
          {row.response_type === 'embed' ? (
            <span>
              Embed: {row.embed_title || row.embed_description || row.message_content || '(empty)'}
            </span>
          ) : (
            <span>{row.message_content}</span>
          )}
        </div>
      ),
    },
    {
      header: 'Status',
      accessor: (row) => (
        <Badge
          variant={row.enabled ? 'default' : 'secondary'}
          className={row.enabled ? 'bg-green-600 hover:bg-green-600' : ''}
        >
          {row.enabled ? 'Enabled' : 'Disabled'}
        </Badge>
      ),
    },
    {
      header: 'Actions',
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
            Edit
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
        <h1 className="text-2xl font-bold">Message Milestone</h1>
        <p className="text-muted-foreground">Loading...</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Message Milestone</h1>

      <div ref={formRef}>
        <Card>
          <CardHeader>
            <CardTitle>{isEdit ? 'Edit Message Milestone' : 'Add Message Milestone'}</CardTitle>
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

              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <label
                    htmlFor="daily-required-count"
                    className="mb-1.5 block text-sm font-medium"
                  >
                    1日あたりの投稿数
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
              </div>

              <div>
                <label htmlFor="pattern" className="mb-1.5 block text-sm font-medium">
                  カウント対象フィルタ <span className="text-muted-foreground">(任意)</span>
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
                </p>
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
                  onValueChange={(v) => setResponseType(v as 'plain' | 'embed')}
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
                  <code>{'{n}'}</code> は1日あたりの投稿数に置き換わります。
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

              {error && <p className="text-sm text-destructive-foreground">{error}</p>}
              <div className="flex items-center gap-2">
                <Button type="submit" disabled={submitting || !canSubmit}>
                  {submitting ? (isEdit ? 'Saving...' : 'Adding...') : isEdit ? 'Save' : 'Add'}
                </Button>
                {isEdit && (
                  <Button type="button" variant="outline" onClick={resetForm} disabled={submitting}>
                    Cancel
                  </Button>
                )}
              </div>
            </form>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Configured Message Milestones</CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={columns}
            data={configs}
            emptyMessage="No message milestones configured"
          />
        </CardContent>
      </Card>
    </div>
  )
}
