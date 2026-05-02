import { afterEach, describe, it, expect, vi } from 'vitest'
import { clientFetch } from '@/lib/client-api'

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

describe('clientFetch', () => {
  it('returns parsed JSON on 2xx', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ hello: 'world' }),
    }) as unknown as typeof fetch

    const { data, error } = await clientFetch<{ hello: string }>('/auto-reaction')
    expect(error).toBeNull()
    expect(data).toEqual({ hello: 'world' })
  })

  it('extracts detail from error JSON body', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      text: () => Promise.resolve(JSON.stringify({ detail: 'Not authenticated' })),
    }) as unknown as typeof fetch

    const { data, error } = await clientFetch('/auth/me')
    expect(data).toBeNull()
    expect(error).toBe('Not authenticated')
  })

  it('falls back to raw text when body is not JSON', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      text: () => Promise.resolve('Internal error'),
    }) as unknown as typeof fetch

    const { error } = await clientFetch('/whatever')
    expect(error).toBe('Internal error')
  })
})
