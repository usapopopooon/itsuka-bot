import { API_BASE } from './constants'

export async function clientFetch<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<{ data: T | null; error: string | null }> {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    })
    if (!response.ok) {
      const text = await response.text()
      let errorMessage: string
      try {
        const parsed = JSON.parse(text)
        errorMessage = parsed.detail || parsed.message || text
      } catch {
        errorMessage = text
      }
      return { data: null, error: errorMessage }
    }
    const data = (await response.json()) as T
    return { data, error: null }
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    return { data: null, error: message }
  }
}
