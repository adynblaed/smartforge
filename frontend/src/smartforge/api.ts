// Thin typed fetch wrapper for SmartForge endpoints. Uses the same base URL and
// bearer token as the generated client (VITE_API_URL + localStorage token), so
// it composes with the existing auth flow without requiring client regeneration.

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000"
const API = `${BASE}/api/v1`

// Typed error for `sf` calls. Carries the HTTP status (and the server's
// `detail` when parseable) while keeping the "401 Unauthorized"-style message
// so existing message-based handling keeps working. Also carries the server's
// correlation id (X-Request-ID, API-014) so users can quote a reference code
// when reporting failures. Never includes tokens, auth headers, or the
// request payload.
export class ApiError extends Error {
  readonly status: number
  readonly detail?: string
  readonly requestId?: string

  constructor(
    status: number,
    message: string,
    detail?: string,
    requestId?: string,
  ) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.detail = detail
    this.requestId = requestId
  }
}

// The backend stamps every response with a correlation id. Only this one
// header is ever read off a response — never auth headers.
function requestIdOf(res: Response): string | undefined {
  return res.headers.get("X-Request-ID") ?? undefined
}

// Extract the API's `detail` string from an error response body, if present.
async function errorDetail(res: Response): Promise<string | undefined> {
  const body: unknown = await res.json().catch(() => undefined)
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail?: unknown }).detail
    if (typeof detail === "string") return detail
  }
  return undefined
}

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
    throw new ApiError(
      res.status,
      `Unauthorized (${res.status})`,
      undefined,
      requestIdOf(res),
    )
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
  if (!res.ok)
    throw new ApiError(
      res.status,
      `${res.status} ${res.statusText}`,
      await errorDetail(res),
      requestIdOf(res),
    )
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const sf = {
  get: <T>(p: string) => req<T>(p),
  post: <T>(p: string, body?: unknown) =>
    req<T>(p, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    }),
  patch: <T>(p: string, body?: unknown) =>
    req<T>(p, {
      method: "PATCH",
      body: body ? JSON.stringify(body) : undefined,
    }),
  del: <T>(p: string) => req<T>(p, { method: "DELETE" }),
  // Download a binary response (e.g. a CSV snapshot) with auth applied.
  blob: async (p: string): Promise<Blob> => {
    const res = await fetch(`${API}${p}`, { headers: authHeaders() })
    handleUnauthorized(res, p)
    if (!res.ok)
      throw new ApiError(
        res.status,
        `${res.status} ${res.statusText}`,
        await errorDetail(res),
        requestIdOf(res),
      )
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
    if (!res.ok) {
      const detail = typeof body?.detail === "string" ? body.detail : undefined
      throw new ApiError(
        res.status,
        detail ?? `${res.status} ${res.statusText}`,
        detail,
        requestIdOf(res),
      )
    }
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
