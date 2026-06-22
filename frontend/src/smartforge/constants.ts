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
} as const

/** WebSocket reconnect backoff. */
export const WS_RECONNECT_MS = 4000

/** AI confidence at/below which a human-escalation path is offered. */
export const LOW_CONFIDENCE = 0.6

/** Confidence reported when a customer explicitly escalates from the assistant. */
export const ESCALATION_CONFIDENCE = 0.3
