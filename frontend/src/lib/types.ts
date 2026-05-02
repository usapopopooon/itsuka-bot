export interface GuildsMap {
  [guildId: string]: string
}
export interface ChannelsMap {
  [guildId: string]: { id: string; name: string }[]
}

export interface CustomEmoji {
  id: string
  name: string
  animated: boolean
  format: string // <:name:id> または <a:name:id>
}
export interface CustomEmojisMap {
  [guildId: string]: CustomEmoji[]
}

export interface AutoReactionConfig {
  id: number
  guild_id: string
  channel_id: string
  emojis: string[]
  enabled: boolean
}
