// Pure helpers + tiny presentational pieces for the Data Platform page.
// Kept out of the route file so they are unit-testable (tests-unit/dataPlatform).

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type {
  FreshnessRow,
  FreshnessStatus,
  ReplicationRun,
  ReplicationTableRun,
} from "@/smartforge/platformTypes"

/* ------------------------------------------------------- status → styling */

// Matches the StatusBadge token conventions in smartforge/components.tsx:
// success = fresh, warning = lagging, danger = stale, muted = never loaded.
const FRESHNESS_CLS: Record<FreshnessStatus, string> = {
  fresh: "bg-success/15 text-success border-success/30",
  warning: "bg-warning/15 text-warning border-warning/30",
  stale: "bg-danger/15 text-danger border-danger/30",
  never_loaded: "bg-muted text-muted-foreground border-border",
}

export function freshnessClass(status: string | null | undefined): string {
  return (
    FRESHNESS_CLS[status as FreshnessStatus] ??
    "bg-muted text-muted-foreground border-border"
  )
}

/** Run/manifest status → the same semantic tokens (succeeded/failed/running). */
export function runStatusClass(status: string | null | undefined): string {
  const s = (status ?? "").toLowerCase()
  if (["succeeded", "success", "completed", "published", "passed"].includes(s))
    return "bg-success/15 text-success border-success/30"
  if (["failed", "error", "rejected"].includes(s))
    return "bg-danger/15 text-danger border-danger/30"
  if (["running", "started", "in_progress", "pending"].includes(s))
    return "bg-info/15 text-info border-info/30"
  return "bg-muted text-muted-foreground border-border"
}

export function FreshnessBadge({ status }: { status?: string | null }) {
  const value = status ?? "unknown"
  return (
    <Badge
      variant="outline"
      className={cn("capitalize", freshnessClass(status))}
    >
      {value.replace(/_/g, " ")}
    </Badge>
  )
}

export function RunStatusBadge({ status }: { status?: string | null }) {
  const value = status ?? "unknown"
  return (
    <Badge
      variant="outline"
      className={cn("capitalize", runStatusClass(status))}
    >
      {value.replace(/_/g, " ")}
    </Badge>
  )
}

/* -------------------------------------------------------------- formatting */

/** Watermark lag in minutes → compact human string (42m / 3h 24m / 2d 5h). */
export function formatLag(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "—"
  if (minutes < 1) return "<1m"
  const mins = Math.round(minutes)
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  if (hours < 24) {
    const rem = mins % 60
    return rem ? `${hours}h ${rem}m` : `${hours}h`
  }
  const days = Math.floor(hours / 24)
  const remHours = hours % 24
  return remHours ? `${days}d ${remHours}h` : `${days}d`
}

/** Run duration between two ISO timestamps; open-ended runs show "running". */
export function formatRunDuration(
  startedAt: string | null | undefined,
  completedAt: string | null | undefined,
): string {
  if (!startedAt) return "—"
  const start = new Date(startedAt).getTime()
  if (Number.isNaN(start)) return "—"
  const end = completedAt ? new Date(completedAt).getTime() : Number.NaN
  if (Number.isNaN(end)) return "running"
  const secs = Math.max(0, (end - start) / 1000)
  if (secs < 60) return `${secs.toFixed(1)}s`
  const m = Math.floor(secs / 60)
  const s = Math.round(secs % 60)
  return s ? `${m}m ${s}s` : `${m}m`
}

/** ISO timestamp → readable local string (same convention as Datasources). */
export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString()
}

/** snake_case KPI key → display label ("quality_pass_rate_30d" → "Quality Pass Rate 30d"). */
export function kpiLabel(key: string): string {
  return key.replace(/_/g, " ").replace(/\b[a-z]/g, (c) => c.toUpperCase())
}

/* ------------------------------------------------------------ aggregations */

export interface FreshnessCounts {
  fresh: number
  warning: number
  stale: number
  never_loaded: number
}

/** Bucket freshness rows by status for the health summary tiles. */
export function freshnessCounts(
  rows: Pick<FreshnessRow, "status">[],
): FreshnessCounts {
  const counts: FreshnessCounts = {
    fresh: 0,
    warning: 0,
    stale: 0,
    never_loaded: 0,
  }
  for (const row of rows) {
    if (row.status in counts) counts[row.status] += 1
  }
  return counts
}

export interface RunSummary extends ReplicationRun {
  tables: number
  rows: number
}

/** Join top-level runs with their per-table runs (tables touched, rows moved). */
export function summarizeRuns(
  runs: ReplicationRun[],
  tableRuns: ReplicationTableRun[],
): RunSummary[] {
  const byRun = new Map<string, { tables: number; rows: number }>()
  for (const tr of tableRuns) {
    const agg = byRun.get(tr.run_id) ?? { tables: 0, rows: 0 }
    agg.tables += 1
    agg.rows += tr.rows_loaded_to_postgres ?? tr.rows_extracted ?? 0
    byRun.set(tr.run_id, agg)
  }
  return runs.map((run) => ({
    ...run,
    tables: byRun.get(run.run_id)?.tables ?? 0,
    rows: byRun.get(run.run_id)?.rows ?? 0,
  }))
}
