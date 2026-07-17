// Thin typed fetch wrapper for SmartForge endpoints. Uses the same base URL and
// bearer token as the generated client (VITE_API_URL + localStorage token), so
// it composes with the existing auth flow without requiring client regeneration.

/** ONE base-URL rule for every client (sf wrapper AND the generated
 * OpenAPI client import this): explicit VITE_API_URL wins; otherwise dev
 * servers target the local backend and production builds go same-origin
 * ("" — nginx proxies /api), so a missing env var can never silently split
 * auth and data across two different origins. */
export const API_BASE_URL: string =
  import.meta.env.VITE_API_URL ??
  (import.meta.env.DEV ? "http://localhost:8000" : "")
const API = `${API_BASE_URL}/api/v1`

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

// On an AUTHENTICATION failure (401: missing/expired token), mirror the
// generated client: clear the token and bounce to /login (except for
// customer-portal calls, which handle 401 themselves). 403 is
// AUTHORIZATION — a validly-logged-in user lacking a permission — and must
// surface as an error, never nuke the session.
function handleUnauthorized(res: Response, path: string): void {
  if (res.status === 401) {
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
  base: API_BASE_URL,
}

export function wsUrl(path: string): string {
  const u = new URL(`${API}${path}`, window.location.href)
  u.protocol = u.protocol.replace("http", "ws")
  return u.toString()
}

/** Subprotocol label offered alongside the JWT — must match the backend's
 * BEARER_SUBPROTOCOL (app/api/routes/ws.py). */
const WS_BEARER_SUBPROTOCOL = "smartforge.bearer"

/** Open an authenticated WebSocket. The browser API can't set an
 * Authorization header, so the JWT travels in the Sec-WebSocket-Protocol
 * handshake header (never the URL — URLs land in access logs). */
export function openAuthedWebSocket(path: string): WebSocket {
  const token = localStorage.getItem("access_token")
  return token
    ? new WebSocket(wsUrl(path), [WS_BEARER_SUBPROTOCOL, token])
    : new WebSocket(wsUrl(path))
}
