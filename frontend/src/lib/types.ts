export interface GuildsMap {
  [guildId: string]: string
}
export interface ChannelsMap {
  [guildId: string]: { id: string; name: string }[]
}

export interface AutoReactionConfig {
  id: number
  guild_id: string
  channel_id: string
  emojis: string[]
  enabled: boolean
}
