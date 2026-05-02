'use client'

import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { API_BASE } from '@/lib/constants'
import type { AutoReactionConfig, ChannelsMap, CustomEmojisMap, GuildsMap } from '@/lib/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DataTable, type Column } from '@/components/data-table'
import { DeleteButton } from '@/components/delete-button'
import { GuildChannelSelector } from '@/components/guild-channel-selector'
import { ToggleButton } from '@/components/toggle-button'
import { EmojiPicker, renderEmojiToken } from '@/components/emoji-picker'

const MAX_EMOJIS = 20

function resolveGuildName(guilds: GuildsMap, guildId: string) {
  return guilds[guildId] ?? guildId
}

function resolveChannelName(channels: ChannelsMap, guildId: string, channelId: string) {
  const list = channels[guildId] ?? []
  const ch = list.find((c) => c.id === channelId)
  return ch ? `#${ch.name}` : channelId
}

interface AutoReactionListResponse {
  configs: AutoReactionConfig[]
  guilds: GuildsMap
  channels: ChannelsMap
  custom_emojis: CustomEmojisMap
}

export default function AutoReactionPage() {
  const router = useRouter()
  const [configs, setConfigs] = useState<AutoReactionConfig[]>([])
  const [guilds, setGuilds] = useState<GuildsMap>({})
  const [channels, setChannels] = useState<ChannelsMap>({})
  const [customEmojis, setCustomEmojis] = useState<CustomEmojisMap>({})
  const [loading, setLoading] = useState(true)

  const [selectedGuild, setSelectedGuild] = useState('')
  const [selectedChannel, setSelectedChannel] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const guildCustomEmojis = useMemo(
    () => (selectedGuild ? (customEmojis[selectedGuild] ?? []) : []),
    [customEmojis, selectedGuild]
  )

  async function fetchData() {
    const res = await fetch(`${API_BASE}/auto-reaction`)
    if (res.status === 401) {
      router.push('/login')
      return
    }
    const body = (await res.json()) as Partial<AutoReactionListResponse>
    setConfigs(body.configs ?? [])
    setGuilds(body.guilds ?? {})
    setChannels(body.channels ?? {})
    setCustomEmojis(body.custom_emojis ?? {})
    setLoading(false)
  }

  useEffect(() => {
    fetchData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function addEmoji(emoji: string) {
    setPicked((prev) => (prev.length >= MAX_EMOJIS ? prev : [...prev, emoji]))
  }

  function removeEmojiAt(index: number) {
    setPicked((prev) => prev.filter((_, i) => i !== index))
  }

  function resetForm() {
    setSelectedGuild('')
    setSelectedChannel('')
    setPicked([])
    setError('')
  }

  async function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault()
    setError('')
    if (!selectedGuild || !selectedChannel) return
    if (picked.length === 0) return
    setSubmitting(true)
    try {
      const res = await fetch(`${API_BASE}/auto-reaction`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          guild_id: selectedGuild,
          channel_id: selectedChannel,
          emojis: picked,
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.detail || 'Failed to add auto reaction')
        return
      }
      resetForm()
      await fetchData()
      router.refresh()
    } finally {
      setSubmitting(false)
    }
  }

  const columns: Column<AutoReactionConfig>[] = [
    {
      header: 'Server',
      accessor: (row) => resolveGuildName(guilds, row.guild_id),
    },
    {
      header: 'Channel',
      accessor: (row) => resolveChannelName(channels, row.guild_id, row.channel_id),
    },
    {
      header: 'Emojis',
      accessor: (row) =>
        row.emojis.length > 0 ? (
          <span className="inline-flex flex-wrap items-center gap-1">
            {row.emojis.map((emoji, i) => renderEmojiToken(emoji, `${row.id}-${i}`))}
          </span>
        ) : (
          <span className="text-muted-foreground">(none)</span>
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
            endpoint={`${API_BASE}/auto-reaction/${row.id}/toggle`}
            enabled={row.enabled}
            onSuccess={fetchData}
          />
          <DeleteButton endpoint={`${API_BASE}/auto-reaction/${row.id}`} onSuccess={fetchData} />
        </div>
      ),
    },
  ]

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Auto Reaction</h1>
        <p className="text-muted-foreground">Loading...</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Auto Reaction</h1>

      <Card>
        <CardHeader>
          <CardTitle>Add Auto Reaction</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <GuildChannelSelector
              guilds={guilds}
              channels={channels}
              selectedGuild={selectedGuild}
              selectedChannel={selectedChannel}
              onGuildChange={(id) => {
                setSelectedGuild(id)
                setPicked([])
              }}
              onChannelChange={setSelectedChannel}
            />
            <div>
              <label className="mb-1.5 block text-sm font-medium">絵文字</label>
              {selectedGuild ? (
                <EmojiPicker
                  selected={picked}
                  customEmojis={guildCustomEmojis}
                  onAdd={addEmoji}
                  onRemove={removeEmojiAt}
                  maxCount={MAX_EMOJIS}
                />
              ) : (
                <p className="rounded-md border border-dashed border-input px-3 py-4 text-center text-sm text-muted-foreground">
                  まずサーバーを選択してください
                </p>
              )}
            </div>
            {error && <p className="text-sm text-destructive-foreground">{error}</p>}
            <div>
              <Button
                type="submit"
                disabled={submitting || !selectedGuild || !selectedChannel || picked.length === 0}
              >
                {submitting ? 'Adding...' : 'Add'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Configured Auto Reactions</CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable columns={columns} data={configs} emptyMessage="No auto reactions configured" />
        </CardContent>
      </Card>
    </div>
  )
}
