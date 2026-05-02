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
  /** 正規表現 (Python re.search 用)。null/空なら全件にマッチ。 */
  pattern: string | null
  enabled: boolean
}
