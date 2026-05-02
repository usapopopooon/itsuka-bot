'use client'

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { GuildsMap, ChannelsMap } from '@/lib/types'

interface GuildChannelSelectorProps {
  guilds: GuildsMap
  channels: ChannelsMap
  selectedGuild: string
  selectedChannel: string
  onGuildChange: (guildId: string) => void
  onChannelChange: (channelId: string) => void
  guildLabel?: string
  channelLabel?: string
}

export function GuildChannelSelector({
  guilds,
  channels,
  selectedGuild,
  selectedChannel,
  onGuildChange,
  onChannelChange,
  guildLabel = 'Server',
  channelLabel = 'Channel',
}: GuildChannelSelectorProps) {
  const guildEntries = Object.entries(guilds)
  const filteredChannels = selectedGuild ? (channels[selectedGuild] ?? []) : []

  return (
    <div className="flex gap-4">
      <div className="flex-1">
        <label className="text-sm font-medium mb-1.5 block">{guildLabel}</label>
        <Select
          value={selectedGuild}
          onValueChange={(v) => {
            onGuildChange(v)
            onChannelChange('')
          }}
        >
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Select server" />
          </SelectTrigger>
          <SelectContent>
            {guildEntries.map(([id, name]) => (
              <SelectItem key={id} value={id}>
                {name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex-1">
        <label className="text-sm font-medium mb-1.5 block">{channelLabel}</label>
        <Select value={selectedChannel} onValueChange={onChannelChange} disabled={!selectedGuild}>
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Select channel" />
          </SelectTrigger>
          <SelectContent>
            {filteredChannels.map((ch) => (
              <SelectItem key={ch.id} value={ch.id}>
                {ch.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  )
}
