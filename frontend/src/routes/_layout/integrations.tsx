import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { sf } from "@/smartforge/api"
import { POLL } from "@/smartforge/constants"
import { KpiTile, PageHeader, Panel, StatusBadge } from "@/smartforge/components"
import type { IntegrationsStatus, Page, SyncEvent } from "@/smartforge/types"

export const Route = createFileRoute("/_layout/integrations")({
  component: IntegrationsPage,
  head: () => ({ meta: [{ title: "Integrations - SmartForge" }] }),
})

function IntegrationsPage() {
  const qc = useQueryClient()
  const [system, setSystem] = useState<"erp" | "mes">("erp")
  const { data: status } = useQuery({
    queryKey: ["integrations-status"],
    queryFn: () => sf.get<IntegrationsStatus>("/integrations/status"),
    refetchInterval: POLL.medium,
  })
  const { data: events } = useQuery({
    queryKey: ["integration-events", system],
    queryFn: () => sf.get<Page<SyncEvent>>(`/integrations/events?system=${system}`),
  })
  const { data: kpis } = useQuery({
    queryKey: ["factory-kpis"],
    queryFn: () => sf.get<Record<string, number>>("/factory/kpis"),
    refetchInterval: POLL.medium,
  })
  const sync = useMutation({
    mutationFn: (sys: "erp" | "mes") => sf.post(`/integrations/${sys}/sync`),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["integrations-status"] })
      qc.invalidateQueries({ queryKey: ["integration-events"] })
    },
  })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Integrations & Operations"
        description="ERP/MES sync status and cross-system operations overview."
      />

      <div className="grid gap-4 sm:grid-cols-2">
        {(["erp", "mes"] as const).map((sys) => {
          const s = status?.[sys]
          return (
            <Panel
              key={sys}
              title={`${sys.toUpperCase()} Adapter`}
              action={<StatusBadge value={s?.connected ? "running" : "offline"} />}
            >
              <div className="grid grid-cols-3 gap-3 text-sm">
                <div>
                  <div className="text-xs text-muted-foreground">Events</div>
                  <div className="text-lg font-semibold">{s?.total_events ?? 0}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Failed</div>
                  <div className="text-lg font-semibold text-danger">
                    {s?.failed_records ?? 0}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Last sync</div>
                  <div className="text-xs">
                    {s?.last_successful_sync
                      ? new Date(s.last_successful_sync).toLocaleTimeString()
                      : "—"}
                  </div>
                </div>
              </div>
              <Button
                size="sm"
                className="mt-3"
                disabled={sync.isPending}
                onClick={() => sync.mutate(sys)}
              >
                Run {sys.toUpperCase()} sync
              </Button>
            </Panel>
          )
        })}
      </div>

      <Panel title="Operations Overview">
        <div className="grid gap-4 sm:grid-cols-4">
          <KpiTile label="Open Work Orders" value={kpis?.open_work_orders ?? 0} />
          <KpiTile label="Active Alerts" value={kpis?.active_alerts ?? 0} />
          <KpiTile
            label="Avg OEE"
            value={`${((kpis?.avg_oee ?? 0) * 100).toFixed(1)}%`}
          />
          <KpiTile label="Delayed Orders" value={kpis?.delayed_orders ?? 0} />
        </div>
      </Panel>

      <Panel
        title="Sync Events"
        action={
          <div className="flex gap-1">
            {(["erp", "mes"] as const).map((s) => (
              <Button
                key={s}
                size="sm"
                variant={system === s ? "default" : "outline"}
                onClick={() => setSystem(s)}
              >
                {s.toUpperCase()}
              </Button>
            ))}
          </div>
        }
      >
        <table className="w-full text-sm">
          <thead className="text-left text-muted-foreground">
            <tr className="border-b">
              <th className="py-2 pr-4">Entity</th>
              <th className="py-2 pr-4">Direction</th>
              <th className="py-2 pr-4">Status</th>
              <th className="py-2">Detail</th>
            </tr>
          </thead>
          <tbody>
            {events?.data.map((e) => (
              <tr key={e.id} className="border-b">
                <td className="py-2 pr-4">{e.entity_type}</td>
                <td className="py-2 pr-4 capitalize">{e.direction}</td>
                <td className="py-2 pr-4">
                  <StatusBadge value={e.status === "failed" ? "high" : "running"} />
                </td>
                <td className="py-2 text-muted-foreground">{e.detail ?? "—"}</td>
              </tr>
            ))}
            {events?.data.length === 0 && (
              <tr>
                <td colSpan={4} className="py-4 text-muted-foreground">
                  No sync events yet — run a sync above.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Panel>
    </div>
  )
}
