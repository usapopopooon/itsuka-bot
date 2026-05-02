'use client'

import { useMemo, useState } from 'react'
import type { CustomEmoji } from '@/lib/types'
import { UNICODE_EMOJI_SUGGESTIONS } from '@/lib/emoji-suggestions'
import { cn } from '@/lib/utils'

interface EmojiPickerProps {
  selected: string[]
  customEmojis: CustomEmoji[]
  onAdd: (emoji: string) => void
  onRemove: (index: number) => void
  maxCount: number
}

function customEmojiUrl(id: string, animated: boolean): string {
  const ext = animated ? 'gif' : 'png'
  return `https://cdn.discordapp.com/emojis/${id}.${ext}?size=44&quality=lossless`
}

function isCustomFormat(s: string): { id: string; animated: boolean } | null {
  const m = s.match(/^<(a)?:[^:]+:(\d+)>$/)
  if (!m) return null
  return { id: m[2], animated: !!m[1] }
}

function renderEmoji(emoji: string, key: string | number) {
  const custom = isCustomFormat(emoji)
  if (custom) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        key={key}
        src={customEmojiUrl(custom.id, custom.animated)}
        alt={emoji}
        className="inline-block size-5 align-text-bottom"
      />
    )
  }
  return (
    <span key={key} className="text-lg leading-none">
      {emoji}
    </span>
  )
}

export function EmojiPicker({
  selected,
  customEmojis,
  onAdd,
  onRemove,
  maxCount,
}: EmojiPickerProps) {
  const [filter, setFilter] = useState('')
  const atLimit = selected.length >= maxCount

  const filteredCustom = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return customEmojis
    return customEmojis.filter((e) => e.name.toLowerCase().includes(q))
  }, [filter, customEmojis])

  return (
    <div className="space-y-3">
      {/* 選択済みチップ */}
      <div className="min-h-10 flex flex-wrap items-center gap-2 rounded-md border border-input bg-transparent px-3 py-2">
        {selected.length === 0 ? (
          <span className="text-sm text-muted-foreground">
            下のリストから絵文字を選んでください (最大 {maxCount} 個)
          </span>
        ) : (
          selected.map((emoji, i) => (
            <button
              key={`${emoji}-${i}`}
              type="button"
              onClick={() => onRemove(i)}
              className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-1 text-sm text-secondary-foreground hover:bg-secondary/80"
              title="クリックで削除"
            >
              {renderEmoji(emoji, i)}
              <span className="text-xs text-muted-foreground">×</span>
            </button>
          ))
        )}
      </div>

      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {selected.length} / {maxCount}
        </span>
        <input
          type="text"
          placeholder="カスタム絵文字を名前で検索"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="h-8 w-56 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
        />
      </div>

      {/* カスタム絵文字 */}
      <div>
        <div className="mb-1.5 text-xs font-medium text-muted-foreground">
          このサーバーのカスタム絵文字 ({filteredCustom.length})
        </div>
        {filteredCustom.length === 0 ? (
          <div className="rounded-md border border-dashed border-input px-3 py-4 text-center text-xs text-muted-foreground">
            このサーバーには利用可能なカスタム絵文字がありません
          </div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {filteredCustom.map((e) => (
              <button
                key={e.id}
                type="button"
                disabled={atLimit}
                onClick={() => onAdd(e.format)}
                title={`:${e.name}:`}
                className={cn(
                  'flex size-9 items-center justify-center rounded-md border border-transparent bg-muted/40 transition-colors hover:bg-accent hover:text-accent-foreground',
                  atLimit && 'cursor-not-allowed opacity-40 hover:bg-muted/40'
                )}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={customEmojiUrl(e.id, e.animated)} alt={e.name} className="size-5" />
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Unicode 絵文字 */}
      <div>
        <div className="mb-1.5 text-xs font-medium text-muted-foreground">
          標準 (Unicode) 絵文字
        </div>
        <div className="space-y-2">
          {UNICODE_EMOJI_SUGGESTIONS.map((cat) => (
            <div key={cat.label}>
              <div className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground/70">
                {cat.label}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {cat.emojis.map((emoji) => (
                  <button
                    key={emoji}
                    type="button"
                    disabled={atLimit}
                    onClick={() => onAdd(emoji)}
                    className={cn(
                      'flex size-9 items-center justify-center rounded-md border border-transparent bg-muted/40 text-lg transition-colors hover:bg-accent hover:text-accent-foreground',
                      atLimit && 'cursor-not-allowed opacity-40 hover:bg-muted/40'
                    )}
                  >
                    {emoji}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export { renderEmoji as renderEmojiToken }
