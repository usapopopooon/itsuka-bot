'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Switch } from '@/components/ui/switch'

interface ToggleButtonProps {
  endpoint: string
  enabled: boolean
  /** クライアント描画ページから再フェッチするためのフック。
   *  サーバーコンポーネントだけなら router.refresh() で十分だが、
   *  自前の useState ベースの一覧では明示コールが必要。 */
  onSuccess?: () => void
}

export function ToggleButton({ endpoint, enabled, onSuccess }: ToggleButtonProps) {
  const router = useRouter()
  const [loading, setLoading] = useState(false)

  async function handleToggle() {
    setLoading(true)
    try {
      await fetch(endpoint, { method: 'PATCH' })
      onSuccess?.()
      router.refresh()
    } finally {
      setLoading(false)
    }
  }

  return <Switch checked={enabled} onCheckedChange={handleToggle} disabled={loading} />
}
