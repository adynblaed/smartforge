// Thin typed fetch wrapper for SmartForge endpoints. Uses the same base URL and
// bearer token as the generated client (VITE_API_URL + localStorage token), so
// it composes with the existing auth flow without requiring client regeneration.

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000"
const API = `${BASE}/api/v1`

function authHeaders(): HeadersInit {
  const token = localStorage.getItem("access_token")
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// On an auth failure, mirror the generated client: clear the token and bounce
// to /login (except for customer-portal calls, which handle 401 themselves).
function handleUnauthorized(res: Response, path: string): void {
  if (res.status === 401 || res.status === 403) {
    if (!path.startsWith("/customer")) {
      localStorage.removeItem("access_token")
      window.location.href = "/login"
    }
    throw new Error(`Unauthorized (${res.status})`)
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
  })
  handleUnauthorized(res, path)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const sf = {
  get: <T>(p: string) => req<T>(p),
  post: <T>(p: string, body?: unknown) =>
    req<T>(p, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(p: string, body?: unknown) =>
    req<T>(p, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  del: <T>(p: string) => req<T>(p, { method: "DELETE" }),
  // Download a binary response (e.g. a CSV snapshot) with auth applied.
  blob: async (p: string): Promise<Blob> => {
    const res = await fetch(`${API}${p}`, { headers: authHeaders() })
    handleUnauthorized(res, p)
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.blob()
  },
  // Upload multipart form data (e.g. a CSV import); surfaces the API's detail.
  upload: async <T>(p: string, form: FormData): Promise<T> => {
    const res = await fetch(`${API}${p}`, {
      method: "POST",
      headers: authHeaders(),
      body: form,
    })
    handleUnauthorized(res, p)
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(body?.detail ?? `${res.status} ${res.statusText}`)
    return body as T
  },
  base: BASE,
}

export function wsUrl(path: string): string {
  const u = new URL(`${API}${path}`, window.location.href)
  u.protocol = u.protocol.replace("http", "ws")
  // The browser WebSocket API can't set Authorization headers, so the JWT is
  // passed as a query param and validated server-side before the socket opens.
  const token = localStorage.getItem("access_token")
  if (token) u.searchParams.set("token", token)
  return u.toString()
}
