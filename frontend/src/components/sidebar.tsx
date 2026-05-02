'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

const navItems = [{ href: '/dashboard/auto-reaction', label: 'Auto Reaction' }]

export function Sidebar() {
  const pathname = usePathname()
  const router = useRouter()
  const [isLoggingOut, setIsLoggingOut] = useState(false)

  async function handleLogout() {
    if (isLoggingOut) return
    setIsLoggingOut(true)
    try {
      await fetch('/api/v1/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
    } finally {
      router.push('/login')
      router.refresh()
      setIsLoggingOut(false)
    }
  }

  return (
    <aside className="flex h-screen w-64 flex-col border-r border-border bg-card">
      <div className="flex h-14 items-center border-b border-border px-4">
        <h1 className="text-lg font-semibold">Itsuka Bot</h1>
      </div>
      <nav className="flex-1 space-y-1 p-3">
        {navItems.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(item.href)
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'flex items-center rounded-md px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-accent text-accent-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
              )}
            >
              {item.label}
            </Link>
          )
        })}
      </nav>
      <div className="border-t border-border p-3">
        <Button
          type="button"
          variant="outline"
          className="w-full justify-center"
          onClick={handleLogout}
          disabled={isLoggingOut}
        >
          {isLoggingOut ? 'Logging out...' : 'Logout'}
        </Button>
      </div>
    </aside>
  )
}
