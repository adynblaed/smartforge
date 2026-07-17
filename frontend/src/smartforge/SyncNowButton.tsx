// One-click targeted sync trigger, shared by the EDA Recent Updates rows,
// the Sync All action and the MRP grid. Triggers ENQUEUE server-side (a
// single worker drains them sequentially under the pipeline lock), so
// rapid clicks and overlapping tables can never surface a lock conflict.
// Server-side each table gets three attempts with self-healing between
// them; useSyncStatuses polls the live outcome so spinners can resolve to
// "Sync Failed" (with the button back for a retry) instead of spinning.

import { useMutation } from "@tanstack/react-query"
import { RefreshCw } from "lucide-react"
import { useMemo } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import { POLL } from "@/smartforge/constants"
import type {
  SyncStatusEntry,
  SyncStatusResponse,
} from "@/smartforge/platformTypes"
import { REFRESH_FAST, usePlatform } from "@/smartforge/platformUi"

export interface SyncQueued {
  status: "queued" | "already_queued"
  table: string
  queue_depth: number
  triggered_by: string
}

export const queueTableSync = (table: string) =>
  sf.post<SyncQueued>("/platform/sync/table", { table })

/** Live per-table sync outcomes, keyed by UPPERCASED qualified name
 * ("OMEGA.WORK_ORDERS"). Polls fast while a sync is being watched. */
export function useSyncStatuses(watching: boolean) {
  const query = usePlatform<SyncStatusResponse>(
    "sync-status",
    "/platform/sync/status",
    watching ? POLL.syncStatus : REFRESH_FAST,
  )
  const byTable = useMemo(() => {
    const map = new Map<string, SyncStatusEntry>()
    for (const entry of query.data?.data ?? [])
      map.set(entry.table.toUpperCase(), entry)
    return map
  }, [query.data])
  return { byTable, isLoading: query.isLoading }
}

/** True while the tracked sync is still pending server-side. */
export const syncInFlight = (entry: SyncStatusEntry | undefined): boolean =>
  entry?.status === "queued" || entry?.status === "running"

export function SyncNowButton({
  table,
  onStarted,
  showLabel = false,
}: {
  table: string
  /** Called when the sync is accepted (queued or already queued). */
  onStarted?: () => void
  showLabel?: boolean
}) {
  const run = useMutation({
    mutationFn: () => queueTableSync(table),
    onSuccess: (res) => {
      toast.success(
        res.status === "already_queued"
          ? `${table} is already queued`
          : `Sync queued for ${table} (${res.queue_depth} in queue)`,
      )
      onStarted?.()
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Sync failed"),
  })
  return (
    <Button
      size={showLabel ? "sm" : "icon"}
      variant={showLabel ? "outline" : "ghost"}
      className={cn("gap-1.5", showLabel ? "h-8 text-xs" : "size-7")}
      aria-label={`Sync ${table} now`}
      title={`Sync ${table} now`}
      disabled={run.isPending}
      onClick={(event) => {
        event.stopPropagation()
        run.mutate()
      }}
    >
      <RefreshCw className={cn("size-3.5", run.isPending && "animate-spin")} />
      {showLabel && "Sync"}
    </Button>
  )
}
