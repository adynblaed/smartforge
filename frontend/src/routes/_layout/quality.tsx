import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Siren, Ticket as TicketIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { sf } from "@/smartforge/api"
import { POLL } from "@/smartforge/constants"
import { BarTrend, KpiTile, metricTrend, PageHeader, Panel, StatusBadge } from "@/smartforge/components"

// Routable KPI tile wrapper.
const STAT_CLS =
  "block rounded-xl outline-none transition hover:brightness-110 focus-visible:ring-2 focus-visible:ring-ring"
import type { Defect, OeeMetric, Page } from "@/smartforge/types"

export const Route = createFileRoute("/_layout/quality")({
  component: QualityPage,
  head: () => ({ meta: [{ title: "Quality - SmartForge" }] }),
})

function QualityPage() {
  const qc = useQueryClient()
  const { data: oee } = useQuery({
    queryKey: ["oee"],
    queryFn: () => sf.get<Page<OeeMetric>>("/oee"),
  })
  const { data: defects } = useQuery({
    queryKey: ["defects"],
    queryFn: () => sf.get<Page<Defect>>("/defects"),
    refetchInterval: POLL.medium,
  })
  const inspect = useMutation({
    mutationFn: () =>
      sf.post("/inspection-results", {
        part_id: `PART-${Math.floor(2000 + Math.random() * 8000)}`,
      }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["defects"] })
      qc.invalidateQueries({ queryKey: ["inspections"] })
    },
  })

  const rows = oee?.data ?? []
  const avgOee = rows.length
    ? (rows.reduce((s, r) => s + r.oee, 0) / rows.length) * 100
    : 0
  const avgScrap = rows.length
    ? (rows.reduce((s, r) => s + r.scrap_rate, 0) / rows.length) * 100
    : 0
  const chart = rows.map((r, i) => ({
    name: `${r.shift}-${i + 1}`,
    oee: Math.round(r.oee * 100),
  }))
  const scrapCost = (defects?.data ?? []).reduce((s, d) => s + d.scrap_cost, 0)

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Quality & OEE"
        description="Vision inspection, OEE trends, scrap and rework impact."
        actions={
          <Button onClick={() => inspect.mutate()} disabled={inspect.isPending}>
            Run inspection
          </Button>
        }
      />

      <div className="grid gap-4 sm:grid-cols-4">
        <Link to="/analytics" className={STAT_CLS}>
          <KpiTile
            label="Avg OEE"
            value={`${avgOee.toFixed(1)}%`}
            hint="overall effectiveness"
            accent={avgOee >= 80 ? "var(--success)" : avgOee >= 65 ? "var(--warning)" : "var(--danger)"}
            {...metricTrend("oee")}
          />
        </Link>
        <Link to="/analytics" className={STAT_CLS}>
          <KpiTile
            label="Avg Scrap"
            value={`${avgScrap.toFixed(1)}%`}
            hint="of total output"
            accent={avgScrap <= 3 ? "var(--success)" : avgScrap <= 5 ? "var(--warning)" : "var(--danger)"}
            {...metricTrend("scrap")}
          />
        </Link>
        <Link to="/analytics" className={STAT_CLS}>
          <KpiTile
            label="Defects"
            value={defects?.count ?? 0}
            hint="detected this period"
            accent={(defects?.count ?? 0) > 0 ? "var(--danger)" : "var(--success)"}
            {...metricTrend("defects")}
          />
        </Link>
        <Link to="/analytics" className={STAT_CLS}>
          <KpiTile label="Scrap Cost" value={`$${scrapCost.toFixed(0)}`} hint="scrapped value" accent="var(--danger)" {...metricTrend("scrapcost")} />
        </Link>
      </div>

      <Panel title="OEE by Shift / Run">
        <BarTrend data={chart} dataKey="oee" xKey="name" />
      </Panel>

      <Panel title="Defect Risk Panel">
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <p className="text-xs uppercase text-muted-foreground">At-risk lines</p>
            <p className="mt-1 text-sm">
              {avgScrap > 3 ? "Line 01 — elevated scrap" : "No lines above threshold"}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase text-muted-foreground">Scrap cost estimate</p>
            <p className="mt-1 text-lg font-semibold text-danger">
              ${scrapCost.toFixed(0)}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase text-muted-foreground">Suggested intervention</p>
            <p className="mt-1 text-sm">
              {avgScrap > 3
                ? "Tighten inspection sampling; review tooling wear."
                : "Maintain current process controls."}
            </p>
          </div>
        </div>
      </Panel>

      <Panel title="Recent Defects">
        <p className="mb-3 text-xs text-muted-foreground">
          Each defect can be promoted into a correlated Incident + maintenance
          Ticket — tying quality events into the alert ecosystem.
        </p>
        <ul className="divide-y">
          {defects?.data.slice(0, 12).map((d) => (
            <DefectRow key={d.id} defect={d} />
          ))}
          {defects?.data.length === 0 && (
            <li className="py-3 text-sm text-muted-foreground">
              No defects detected.
            </li>
          )}
        </ul>
      </Panel>
    </div>
  )
}

interface Correlation {
  incident_id: string
  incident_title: string
  ticket_id: string
  ticket_code: string
}

function DefectRow({ defect }: { defect: Defect }) {
  const correlate = useMutation({
    mutationFn: () => sf.post<Correlation>(`/defects/${defect.id}/correlate`),
  })
  const link = correlate.data

  return (
    <li className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
      <span className="flex items-center gap-2">
        <StatusBadge value={defect.is_scrap ? "high" : "medium"} />
        {defect.defect_type} {defect.part_id && `· ${defect.part_id}`}
      </span>
      <span className="flex items-center gap-3">
        <span className="text-muted-foreground">${defect.scrap_cost.toFixed(0)}</span>
        {link ? (
          <span className="flex items-center gap-2">
            <Link
              to="/incidents"
              className="inline-flex items-center gap-1 rounded border px-2 py-1 text-[11px] hover:bg-accent"
            >
              <Siren size={12} /> Incident
            </Link>
            <Link
              to="/tickets"
              search={{ ticket: link.ticket_id }}
              className="inline-flex items-center gap-1 rounded border px-2 py-1 text-[11px] font-mono text-primary hover:bg-accent"
            >
              <TicketIcon size={12} /> {link.ticket_code}
            </Link>
          </span>
        ) : (
          <Button
            size="sm"
            variant="outline"
            disabled={correlate.isPending}
            onClick={() => correlate.mutate()}
          >
            <Siren size={13} /> Correlate
          </Button>
        )}
      </span>
    </li>
  )
}
