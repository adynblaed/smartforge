import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router"
import { Ticket as TicketIcon } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { sf } from "@/smartforge/api"
import {
  KpiTile,
  metricTrend,
  PageHeader,
  Panel,
  StatusBadge,
} from "@/smartforge/components"

// Routable KPI tile wrapper.
const STAT_CLS =
  "block rounded-xl outline-none transition hover:brightness-110 focus-visible:ring-2 focus-visible:ring-ring"

import type { Incident, Page, RcaRecord } from "@/smartforge/types"

export const Route = createFileRoute("/_layout/incidents")({
  component: IncidentsPage,
  head: () => ({ meta: [{ title: "Incidents - SmartForge" }] }),
})

function IncidentsPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { data } = useQuery({
    queryKey: ["incidents"],
    queryFn: () => sf.get<Page<Incident>>("/incidents/"),
  })
  const { data: factories } = useQuery({
    queryKey: ["factories"],
    queryFn: () => sf.get<Page<{ id: string }>>("/factories"),
  })
  // incident_id → ticket code, so each incident surfaces its maintenance ticket.
  const { data: ticketMap } = useQuery({
    queryKey: ["tickets-by-incident"],
    queryFn: () => sf.get<Record<string, string>>("/tickets/by-incident"),
  })
  const [selected, setSelected] = useState<string | null>(null)

  // Create-or-get the ticket for an incident, then open it in the Tickets pane.
  const openTicket = useMutation({
    mutationFn: (incidentId: string) =>
      sf.post<{ id: string }>(`/tickets/from-incident/${incidentId}`),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["tickets-by-incident"] })
      navigate({ to: "/tickets", search: { ticket: res.id } })
    },
  })

  const create = useMutation({
    mutationFn: (title: string) =>
      sf.post("/incidents/", {
        title,
        factory_id: factories?.data[0]?.id,
        severity: "high",
      }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["incidents"] }),
  })

  const totalCost = (data?.data ?? []).reduce((s, i) => s + i.estimated_cost, 0)
  const totalDowntime = (data?.data ?? []).reduce(
    (s, i) => s + i.downtime_minutes,
    0,
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Incident Impact"
        description="Outage impact across work orders, downtime cost, and RCA."
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <Link to="/analytics" className={STAT_CLS}>
          <KpiTile
            label="Open Incidents"
            value={data?.data.filter((i) => !i.resolved).length ?? 0}
            {...metricTrend("incidents")}
          />
        </Link>
        <Link to="/analytics" className={STAT_CLS}>
          <KpiTile
            label="Downtime (min)"
            value={totalDowntime}
            accent="var(--warning)"
            {...metricTrend("downtime")}
          />
        </Link>
        <Link to="/analytics" className={STAT_CLS}>
          <KpiTile
            label="Est. Cost Impact"
            value={`$${totalCost.toFixed(0)}`}
            accent="var(--danger)"
            {...metricTrend("costimpact")}
          />
        </Link>
      </div>

      <Panel title="Incidents">
        <ul className="divide-y">
          {data?.data.map((i) => (
            <li key={i.id} className="py-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <StatusBadge value={i.severity} />
                  <span className="font-medium">{i.title}</span>
                  {i.resolved && <StatusBadge value="running" />}
                </div>
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  <span>{i.downtime_minutes} min</span>
                  <span>${i.estimated_cost.toFixed(0)}</span>
                  <span>{i.delayed_orders} delayed orders</span>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setSelected(selected === i.id ? null : i.id)}
                  >
                    RCA
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={openTicket.isPending}
                    onClick={() => openTicket.mutate(i.id)}
                  >
                    <TicketIcon size={13} />
                    {ticketMap?.[i.id] ?? "Open ticket"}
                  </Button>
                </div>
              </div>
              {selected === i.id && <Rca incidentId={i.id} />}
            </li>
          ))}
          {data?.data.length === 0 && (
            <li className="py-3 text-sm text-muted-foreground">
              No incidents logged.
            </li>
          )}
        </ul>
      </Panel>

      <LogIncident
        onCreate={(t) => create.mutate(t)}
        pending={create.isPending}
      />
    </div>
  )
}

function Rca({ incidentId }: { incidentId: string }) {
  const { data } = useQuery({
    queryKey: ["rca", incidentId],
    queryFn: () => sf.get<Page<RcaRecord>>(`/incidents/${incidentId}/rca`),
  })
  return (
    <div className="mt-3 rounded-md border bg-muted/40 p-3 text-sm">
      {data?.data.length === 0 && (
        <p className="text-muted-foreground">No RCA recorded yet.</p>
      )}
      {data?.data.map((r) => (
        <div key={r.id} className="space-y-1">
          <p>
            <span className="font-medium">Root cause:</span> {r.root_cause}
          </p>
          {r.corrective_actions && (
            <p>
              <span className="font-medium">Corrective:</span>{" "}
              {r.corrective_actions}
            </p>
          )}
          {r.timeline_note && (
            <p className="text-xs text-muted-foreground">
              Timeline: {r.timeline_note}
            </p>
          )}
        </div>
      ))}
    </div>
  )
}

function LogIncident({
  onCreate,
  pending,
}: {
  onCreate: (title: string) => void
  pending: boolean
}) {
  const [title, setTitle] = useState("")
  return (
    <Panel title="Log Outage">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (title.trim()) {
            onCreate(title)
            setTitle("")
          }
        }}
      >
        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Describe the outage event…"
        />
        <Button type="submit" disabled={pending}>
          Log
        </Button>
      </form>
    </Panel>
  )
}
