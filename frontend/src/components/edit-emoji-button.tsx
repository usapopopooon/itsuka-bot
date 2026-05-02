'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { API_BASE } from '@/lib/constants'
import type { CustomEmoji } from '@/lib/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { EmojiPicker } from '@/components/emoji-picker'

const MAX_EMOJIS = 20

interface EditEmojiButtonProps {
  configId: number
  currentEmojis: string[]
  customEmojis: CustomEmoji[]
  onSuccess?: () => void
}

export function EditEmojiButton({
  configId,
  currentEmojis,
  customEmojis,
  onSuccess,
}: EditEmojiButtonProps) {
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState<string[]>(currentEmojis)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  function handleOpenChange(next: boolean) {
    setOpen(next)
    if (next) {
      // ダイアログを開く都度、最新の現状にリセットする (キャンセル後の再オープン対策)
      setPicked(currentEmojis)
      setError('')
    }
  }

  function addEmoji(e: string) {
    setPicked((prev) => (prev.length >= MAX_EMOJIS ? prev : [...prev, e]))
  }
  function removeEmojiAt(i: number) {
    setPicked((prev) => prev.filter((_, idx) => idx !== i))
  }

  async function handleSave() {
    setError('')
    setSaving(true)
    try {
      const res = await fetch(`${API_BASE}/auto-reaction/${configId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ emojis: picked }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.detail || 'Failed to update')
        return
      }
      setOpen(false)
      onSuccess?.()
      router.refresh()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          Edit
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>絵文字を編集</DialogTitle>
        </DialogHeader>
        <EmojiPicker
          selected={picked}
          customEmojis={customEmojis}
          onAdd={addEmoji}
          onRemove={removeEmojiAt}
          maxCount={MAX_EMOJIS}
        />
        {error && <p className="text-sm text-destructive-foreground">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving || picked.length === 0}>
            {saving ? 'Saving...' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
