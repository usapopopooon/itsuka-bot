import { cookies } from 'next/headers'

const API_URL = process.env.API_URL || 'http://localhost:8000'

interface FetchOptions extends Omit<RequestInit, 'headers'> {
  headers?: Record<string, string>
}

/**
 * Server-side API fetch wrapper that forwards cookies from Next.js to FastAPI.
 */
export async function apiFetch<T = unknown>(
  path: string,
  options: FetchOptions = {}
): Promise<{ data: T | null; error: string | null; status: number }> {
  const cookieStore = await cookies()
  const cookieHeader = cookieStore.toString()

  const url = `${API_URL}${path}`
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(cookieHeader ? { Cookie: cookieHeader } : {}),
    ...options.headers,
  }

  try {
    const response = await fetch(url, {
      ...options,
      headers,
      cache: 'no-store',
    })

    if (!response.ok) {
      const errorBody = await response.text()
      let errorMessage: string
      try {
        const parsed = JSON.parse(errorBody)
        errorMessage = parsed.detail || parsed.message || errorBody
      } catch {
        errorMessage = errorBody
      }
      return { data: null, error: errorMessage, status: response.status }
    }

    const data = (await response.json()) as T
    return { data, error: null, status: response.status }
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    return { data: null, error: message, status: 0 }
  }
}
