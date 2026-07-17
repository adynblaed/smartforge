import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Loader2, RefreshCw } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { OmegaIcon } from "@/components/Sidebar/OmegaIcon"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { useFeatures } from "@/hooks/useFeatures"
import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import { Loading, PageHeader, Panel } from "@/smartforge/components"
import {
  SYNC_REFRESH_DELAY_MS,
  SYNC_SPINNER_FALLBACK_MS,
} from "@/smartforge/constants"
import {
  FreshnessBadge,
  formatLag,
  RunStatusBadge,
} from "@/smartforge/platform"
import type {
  LakeLoad,
  LakeLoadsResponse,
  ReplicationTable,
  ReplicationTablesResponse,
} from "@/smartforge/platformTypes"
import {
  MiniTable,
  REFRESH_SLOW,
  Section,
  usePlatform,
} from "@/smartforge/platformUi"
import { useSyncStatuses } from "@/smartforge/SyncNowButton"

export const Route = createFileRoute("/_layout/omega")({
  component: OmegaPage,
  head: () => ({ meta: [{ title: "Omega - SmartForge" }] }),
})

// Full read-only catalogue of every Omega (legacy source) table migrated
// into the analytics stores, one section per replication contract with a
// panel per destination: Lake (DuckDB views over the published Parquet)
// and Warehouse (PostgreSQL omega merges). Everything here is DERIVED —
// the contract list, previews and sync ledgers come straight from the
// governed endpoints, so a new table appears automatically the moment a
// seed or migration publishes it (same sources the Logs console and
// freshness views read: manifests + watermarks, always in parity).

// Identical frames for EVERY panel, lake or warehouse: a fixed-height
// table region on top and a fixed-height terminal pinned beneath it — the
// terminal always sits in the same place at the same size, and both views
// share one pagination cap (16 records fetched, scroll within the frame).
const TABLE_FRAME = "h-[19rem]"
const TERMINAL_FRAME = "h-40"
const VISIBLE_ROWS = 16

/** One fixed-format timestamp for every sync-trail line (terminal + table
 * views stay comparable at a glance). */
function stamp(value: string | null | undefined): string {
  if (!value) return "----------- --:--:--"
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return "----------- --:--:--"
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** "Last Updated X hours and N minutes ago" — green while within the
 * hourly sync SLO, red once it ages past an hour (stale territory). */
function LastUpdated({ ts }: { ts: string | null | undefined }) {
  if (!ts) return null
  const parsed = Date.parse(ts)
  if (Number.isNaN(parsed)) return null
  const minutes = Math.max(0, Math.floor((Date.now() - parsed) / 60000))
  const hours = Math.floor(minutes / 60)
  const fresh = minutes <= 60
  return (
    <span
      className={cn(
        "text-xs font-medium",
        fresh ? "text-success" : "text-danger",
      )}
    >
      Last Updated {hours} hours and {minutes % 60} minutes ago
    </span>
  )
}

/** "X hours Y minutes Z seconds" from a seconds estimate. */
function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = Math.floor(totalSeconds % 60)
  return `${hours} hours ${minutes} minutes ${seconds} seconds`
}

interface SyncEstimate {
  table: string
  current_rows: number
  estimated_new_rows: number
  estimated_seconds: number
  basis: string
}

/**
 * Targeted, user-confirmed sync of one contracted table. The confirmation
 * shows the pre-sync estimate (history-derived, never touching the
 * source); Yes triggers the audited, single-flight pipeline run — the
 * same event the Logs console, Service Tables and this catalogue's
 * ledgers all read back.
 */
function SyncTableButton({
  table,
  onStarted,
}: {
  table: string
  onStarted?: () => void
}) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const estimate = useQuery({
    queryKey: ["omega", "sync-estimate", table],
    queryFn: () =>
      sf.get<SyncEstimate>(
        `/platform/sync/estimate?table=${encodeURIComponent(table)}`,
      ),
    enabled: open,
    retry: false,
  })
  const run = useMutation({
    mutationFn: () =>
      sf.post<{ status: string; triggered_by: string; queue_depth: number }>(
        "/platform/sync/table",
        { table },
      ),
    onSuccess: (res) => {
      toast.success(
        res.status === "already_queued"
          ? `${table} is already queued`
          : `Sync queued for ${table} — triggered by ${res.triggered_by}`,
      )
      setOpen(false)
      onStarted?.()
      // The pipeline lands asynchronously; refresh the catalogue, the
      // freshness views and the log consoles once it has had a moment.
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["data-platform"] })
        queryClient.invalidateQueries({ queryKey: ["omega"] })
        queryClient.invalidateQueries({ queryKey: ["logs"] })
      }, SYNC_REFRESH_DELAY_MS)
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Sync failed"),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline" className="h-7 gap-1.5 text-xs">
          <RefreshCw className="size-3.5" /> Sync
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Are you sure you want to sync this table?</DialogTitle>
          <DialogDescription>
            {table} — a targeted, single-flight pipeline run (published to the
            lake, merged into the warehouse, reconciled, watermark last). The
            trigger is audited under your account.
          </DialogDescription>
        </DialogHeader>
        {estimate.isPending ? (
          <Loading label="Estimating…" />
        ) : estimate.isError || !estimate.data ? (
          <p className="text-sm text-muted-foreground">
            No estimate available (stores unreachable) — the sync can still run.
          </p>
        ) : (
          <div className="flex flex-col gap-1.5 rounded-md border bg-muted/30 p-3 text-sm">
            <p>
              <span className="font-medium">Estimated Sync Time:</span>{" "}
              {formatDuration(estimate.data.estimated_seconds)}
            </p>
            <p>
              <span className="font-medium">Current Record Count:</span>{" "}
              {estimate.data.current_rows.toLocaleString()}
            </p>
            <p>
              <span className="font-medium">Estimated New Record Count:</span>{" "}
              {estimate.data.estimated_new_rows.toLocaleString()}
            </p>
            <p className="text-xs text-muted-foreground">
              basis: {estimate.data.basis}
            </p>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button disabled={run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? "Starting…" : "Yes, sync table"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Preview rows straight from the lake view (both stores derive from the
 * same immutable publication, SEED-009 — this preview is the data). */
function LakePreview({ destination }: { destination: string }) {
  const rows = useQuery({
    queryKey: ["omega", "lake-preview", destination],
    queryFn: () =>
      sf.get<{ data: Record<string, unknown>[]; count: number }>(
        `/lake/datasets/omega.${destination}?limit=${VISIBLE_ROWS}`,
      ),
    staleTime: REFRESH_SLOW,
    retry: false,
  })
  // Loading/empty states occupy the same fixed frame as the data table so
  // the terminal below never shifts.
  if (rows.isPending)
    return (
      <div className={cn("rounded-md border", TABLE_FRAME)}>
        <Loading label="Querying DuckDB…" />
      </div>
    )
  if (rows.isError || !rows.data)
    return (
      <p
        className={cn(
          "rounded-md border border-dashed px-3 py-4 text-xs text-muted-foreground",
          TABLE_FRAME,
        )}
      >
        Lake view not synced yet — run a seed or sync.
      </p>
    )
  const data = rows.data.data
  // Dynamic columns from the actual replicated schema: business columns
  // first, capped so every table renders in the same compact footprint.
  const columns = Object.keys(data[0] ?? {})
    .filter((key) => !key.startsWith("_"))
    .slice(0, 6)
  return (
    <div className={cn("overflow-auto rounded-md border", TABLE_FRAME)}>
      <table className="w-full border-collapse text-xs">
        <thead className="sticky top-0 z-10 bg-muted/95">
          <tr>
            {columns.map((column) => (
              <th
                key={column}
                className="whitespace-nowrap border-b border-r px-2 py-1.5 text-left font-semibold uppercase tracking-wide text-muted-foreground last:border-r-0"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.length === 0 && (
            <tr>
              <td
                colSpan={columns.length || 1}
                className="px-3 py-4 text-center text-muted-foreground"
              >
                View synced, zero rows.
              </td>
            </tr>
          )}
          {data.map((row, i) => (
            <tr key={i} className="odd:bg-muted/20">
              {columns.map((column) => (
                <td
                  key={column}
                  className="max-w-[180px] truncate border-b border-r px-2 py-1 last:border-r-0"
                  title={String(row[column] ?? "")}
                >
                  {row[column] == null || row[column] === ""
                    ? "—"
                    : String(row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Terminal-style sync trail (same visual grammar as the Logs console —
 * and the same underlying records, so the two always agree). Timestamps
 * lead every line in one fixed format; 16 lines before scrolling. */
function SyncTerminal({ lines }: { lines: string[] }) {
  return (
    <div
      className={cn(
        "overflow-auto rounded-md bg-[#0b0f17] px-3 py-2 font-mono text-[11px] leading-relaxed",
        TERMINAL_FRAME,
      )}
    >
      {lines.length === 0 && (
        <p className="text-zinc-400">no sync events recorded yet</p>
      )}
      {lines.map((line) => (
        <p
          key={line}
          className="whitespace-nowrap text-zinc-100/90"
          title={line}
        >
          <span className="text-emerald-400">❯</span>{" "}
          <span className="text-zinc-400/80">{line.slice(0, 19)}</span>
          {line.slice(19)}
        </p>
      ))}
    </div>
  )
}

function OmegaTableSection({
  contract,
  loads,
  canSync,
}: {
  contract: ReplicationTable
  loads: LakeLoad[]
  canSync: boolean
}) {
  // Sync-in-flight feedback: after "Yes, sync table" the Last Updated
  // readout becomes a spinner until the watermark actually advances
  // (freshness polls every 30s). The server retries each sync three times
  // with self-healing between attempts; we poll its live status so a table
  // that exhausts its retries resolves to a visible "Sync Failed" — with
  // the Sync button still there for another try — instead of spinning
  // forever. A generous timeout remains as the last-ditch fallback.
  const [syncing, setSyncing] = useState(false)
  const [failed, setFailed] = useState(false)
  const { byTable } = useSyncStatuses(syncing)
  const liveStatus = byTable.get(contract.table.toUpperCase())
  const previousStamp = useRef(contract.last_published_at)
  useEffect(() => {
    if (syncing && previousStamp.current !== contract.last_published_at) {
      setSyncing(false)
      setFailed(false)
    }
    previousStamp.current = contract.last_published_at
  }, [contract.last_published_at, syncing])
  useEffect(() => {
    if (!syncing || liveStatus?.status !== "failed") return
    setSyncing(false)
    setFailed(true)
    toast.error(
      `Sync failed for ${contract.table} after ${liveStatus.attempts} attempts` +
        `${liveStatus.error ? ` (${liveStatus.error})` : ""} — you can retry.`,
    )
  }, [syncing, liveStatus, contract.table])
  useEffect(() => {
    if (!syncing) return
    const timeout = setTimeout(
      () => setSyncing(false),
      SYNC_SPINNER_FALLBACK_MS,
    )
    return () => clearTimeout(timeout)
  }, [syncing])
  const startSync = () => {
    setFailed(false)
    setSyncing(true)
  }

  const recent = loads
    .filter((load) => load.destination === contract.destination)
    .slice(0, VISIBLE_ROWS)
  const lakeLines = recent.map(
    (load) =>
      `${stamp(load.published_at)}  sync ${load.load_id} · ${load.row_count ?? 0} rows · ${load.file_count ?? 0} file(s) [${load.status}]`,
  )
  const warehouseLines = [
    `${stamp(contract.last_published_at)}  watermark · lag ${formatLag(contract.lag_minutes)} · ${contract.status ?? "unknown"}`,
    ...recent.map(
      (load) =>
        `${stamp(load.published_at)}  merge omega.${contract.destination} · ${load.row_count ?? 0} rows (${contract.strategy}) [${load.status}]`,
    ),
  ].slice(0, VISIBLE_ROWS)

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold">{contract.table}</h2>
        <Badge variant="outline" className="text-xs">
          → {contract.destination}
        </Badge>
        <Badge variant="outline" className="text-xs capitalize">
          {contract.cadence}
        </Badge>
        {contract.status && <FreshnessBadge status={contract.status} />}
        {syncing ? (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" /> syncing…
            {liveStatus?.status === "running" &&
              liveStatus.attempts > 1 &&
              ` retry ${liveStatus.attempts}/3`}
          </span>
        ) : failed ? (
          <span className="text-xs font-medium text-danger">
            Sync Failed — retry with the Sync button
          </span>
        ) : (
          <LastUpdated ts={contract.last_published_at} />
        )}
        {!contract.enabled && (
          <Badge variant="outline" className="text-xs opacity-60">
            disabled
          </Badge>
        )}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        {/* destination tints: Lake reads blue, Warehouse reads green */}
        <Panel
          className="bg-gradient-to-br from-sky-500/10 via-card to-card"
          title={`Lake · omega.${contract.destination}`}
          action={
            <div className="flex items-center gap-2">
              {canSync && (
                <SyncTableButton table={contract.table} onStarted={startSync} />
              )}
              <Badge variant="outline" className="text-xs">
                read-only view
              </Badge>
            </div>
          }
        >
          <div className="flex flex-col gap-2">
            <LakePreview destination={contract.destination} />
            <SyncTerminal lines={lakeLines} />
          </div>
        </Panel>
        <Panel
          className="bg-gradient-to-br from-emerald-500/10 via-card to-card"
          title={`Warehouse · omega.${contract.destination}`}
          action={
            <div className="flex items-center gap-2">
              {canSync && (
                <SyncTableButton table={contract.table} onStarted={startSync} />
              )}
              <Badge variant="outline" className="text-xs">
                merge ledger
              </Badge>
            </div>
          }
        >
          <div className="flex flex-col gap-2">
            <MiniTable
              rows={recent}
              rowKey={(load, i) => `${load.load_id}-${i}`}
              empty="No loads merged yet — run a seed or sync."
              maxHeightClass={TABLE_FRAME}
              cols={[
                {
                  key: "synced",
                  label: "Synced",
                  render: (load) => (
                    <span className="font-mono text-xs">
                      {stamp(load.published_at)}
                    </span>
                  ),
                },
                {
                  key: "load",
                  label: "Load",
                  render: (load) => (
                    <span className="font-mono text-xs" title={load.load_id}>
                      {load.load_id.slice(0, 16)}
                    </span>
                  ),
                },
                {
                  key: "rows",
                  label: "Rows",
                  align: "right",
                  render: (load) => load.row_count?.toLocaleString() ?? "—",
                },
                {
                  key: "scn",
                  label: "SCN",
                  align: "right",
                  render: (load) => String(load.scn ?? "—"),
                },
                {
                  key: "status",
                  label: "Status",
                  render: (load) => <RunStatusBadge status={load.status} />,
                },
              ]}
            />
            <SyncTerminal lines={warehouseLines} />
          </div>
        </Panel>
      </div>
    </section>
  )
}

function OmegaPage() {
  const tables = usePlatform<ReplicationTablesResponse>(
    "replication-tables",
    "/platform/replication/tables",
  )
  const loads = usePlatform<LakeLoadsResponse>(
    ["omega", "lake-loads"],
    "/lake/loads",
    REFRESH_SLOW,
  )
  const { enabled: featureEnabled } = useFeatures()
  const canSync = featureEnabled("platform_ops")

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon={<OmegaIcon className="size-5" />}
        title="Omega"
        description="Every Omega (legacy) table migrated into the analytics stores — read-only, per destination, with its live sync trail. New tables appear here automatically after each seed or migration."
      />
      <Section query={tables}>
        {(res) => {
          const sorted = [...res.data].sort((a, b) =>
            a.table.localeCompare(b.table),
          )
          const loadsByTable = loads.data?.data ?? []
          return (
            <div className="flex flex-col gap-8">
              {sorted.length === 0 && (
                <p className="rounded-lg border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
                  No replication contracts registered yet.
                </p>
              )}
              {sorted.map((contract) => (
                <OmegaTableSection
                  key={contract.table}
                  contract={contract}
                  loads={loadsByTable}
                  canSync={canSync}
                />
              ))}
            </div>
          )
        }}
      </Section>
    </div>
  )
}
