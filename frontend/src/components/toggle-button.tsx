'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Switch } from '@/components/ui/switch'

interface ToggleButtonProps {
  endpoint: string
  enabled: boolean
}

export function ToggleButton({ endpoint, enabled }: ToggleButtonProps) {
  const router = useRouter()
  const [loading, setLoading] = useState(false)

  async function handleToggle() {
    setLoading(true)
    try {
      await fetch(endpoint, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !enabled }),
      })
      router.refresh()
    } finally {
      setLoading(false)
    }
  }

  return <Switch checked={enabled} onCheckedChange={handleToggle} disabled={loading} />
}
