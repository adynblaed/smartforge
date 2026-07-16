// Single place for structured client-side error logging. Everything funnels
// through logClientError so a real reporter (e.g. Sentry) can be attached
// later in exactly one spot. Never logs auth tokens.

// Redact anything that looks like a bearer token before it reaches the console.
function scrub(text: string): string {
  return text.replace(/Bearer\s+[\w.~+/=-]+/gi, "Bearer [redacted]")
}

function messageOf(error: unknown): string {
  try {
    if (error instanceof Error) return error.message
    if (typeof error === "string") return error
    return String(error)
  } catch {
    return "<unprintable error>"
  }
}

export function logClientError(scope: string, error: unknown): void {
  // Logging must never throw — it is called from error paths.
  try {
    console.error("[smartforge]", scope, scrub(messageOf(error)), error)
  } catch {
    // Swallow: a broken console must not mask the original failure.
  }
}

let installed = false

// Catch-alls for errors that escape React and TanStack entirely
// (event handlers, async gaps, third-party code). Idempotent.
export function installGlobalErrorLogging(): void {
  if (installed) return
  installed = true
  window.addEventListener("error", (event) => {
    logClientError("window", event.error ?? event.message)
  })
  window.addEventListener("unhandledrejection", (event) => {
    logClientError("unhandledrejection", event.reason)
  })
}
