import { describe, it, expect } from 'vitest'
import { cn } from '@/lib/utils'

describe('cn', () => {
  it('merges class names', () => {
    expect(cn('px-2', 'py-1')).toBe('px-2 py-1')
  })

  it('lets later tailwind classes override earlier ones', () => {
    // tailwind-merge は同じ系統の最後を優先する
    expect(cn('px-2', 'px-4')).toBe('px-4')
  })

  it('handles falsy entries', () => {
    expect(cn('a', false, undefined, null, 'b')).toBe('a b')
  })
})
