/**
 * Centralized timing + thresholds so cadences are consistent across the app and
 * tunable from one place (avoids scattered magic numbers).
 */
export const POLL = {
  /** Live-ish dashboards (command center, machines, customer orders). */
  fast: 5000,
  /** Operational tables that change less often (work orders, quality, etc.). */
  medium: 8000,
  /** Background refresh when a WebSocket is already streaming updates. */
  slow: 15000,
  /** Polling fallback when the realtime socket is unavailable. */
  realtimeFallback: 4000,
  /** Live sync-status watch while a user-triggered table sync is running. */
  syncStatus: 4000,
} as const

/** How long an in-flight sync spinner may run before the UI falls back to
 * the last-known state (matches the server's lock-wait budget). */
export const SYNC_SPINNER_FALLBACK_MS = 600_000

/** Post-trigger delay before refreshing catalogue/log queries — long enough
 * for a queued sync to start writing control-table evidence. */
export const SYNC_REFRESH_DELAY_MS = 6000

/** WebSocket reconnect backoff. */
export const WS_RECONNECT_MS = 4000

/** AI confidence at/below which a human-escalation path is offered. */
export const LOW_CONFIDENCE = 0.6

/** Confidence reported when a customer explicitly escalates from the assistant. */
export const ESCALATION_CONFIDENCE = 0.3
