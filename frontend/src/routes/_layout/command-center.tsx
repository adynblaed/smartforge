import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { useMemo } from "react"
import {
  AlertTriangle,
  ChevronRight,
  Gauge,
  PackageCheck,
  SlidersHorizontal,
} from "lucide-react"
import type { ReactNode } from "react"

import useAuth from "@/hooks/useAuth"
import { sf } from "@/smartforge/api"
import { POLL } from "@/smartforge/constants"
import {
  KpiTile,
  Loading,
  PageHeader,
  Panel,
  StatusBadge,
  healthColor,
  metricTrend,
  userDisplayName,
} from "@/smartforge/components"
import { GlobalOperations } from "@/smartforge/GlobalOperations"
import type { CommandCenter, Page, PurchaseOrder } from "@/smartforge/types"

export const Route = createFileRoute("/_layout/command-center")({
  component: CommandCenterPage,
  head: () => ({ meta: [{ title: "Command Center - SmartForge" }] }),
})

// Routable stat tile wrapper: blocky, subtle hover lift.
const STAT_CLS =
  "block rounded-xl outline-none transition hover:brightness-110 focus-visible:ring-2 focus-visible:ring-ring"

function greetingFor(hour: number): string {
  if (hour < 12) return "Good morning"
  if (hour < 18) return "Good afternoon"
  return "Good evening"
}

// Courteous, professional greeting variants — randomized per visit alongside the
// time-aware one.
const GREETINGS = ["Greetings", "Hello", "Hi", "Welcome back"]
const pick = <T,>(arr: T[]): T => arr[Math.floor(Math.random() * arr.length)]

function CommandCenterPage() {
  const { user } = useAuth()
  const { data, isLoading } = useQuery({
    queryKey: ["command-center"],
    queryFn: () => sf.get<CommandCenter>("/command-center"),
    refetchInterval: POLL.fast,
  })
  const { data: pos } = useQuery({
    queryKey: ["purchase-orders"],
    queryFn: () => sf.get<Page<PurchaseOrder>>("/purchase-orders"),
    refetchInterval: POLL.slow,
  })

  const k = data?.kpis ?? {}
  const openPOs = (pos?.data ?? []).filter((p) => p.status === "open").length
  // A varied, personalized greeting chosen once per visit/refresh.
  const greetingLine = useMemo(() => {
    const word = pick([greetingFor(new Date().getHours()), ...GREETINGS])
    const named = userDisplayName(user)
    const name = named === "there" ? "Operator" : pick([named, named, "Operator"])
    return `${word}, ${name}`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="text-base font-medium text-info">{greetingLine}</p>
        <PageHeader
          className="mt-1"
          title="Command Center"
          description="Real-time factory health, production, maintenance, and customer impact."
        />
      </div>

      {/* Global logistics network — click a carrier to trace its lane to Reno. */}
      <GlobalOperations className="h-[380px]" />

      {isLoading && <Loading label="Loading command center…" />}

      {/* Stats grouped by the menu section their detail pages live under. */}
      <div className="flex flex-col gap-6">
        <StatGroup
          icon={<Gauge size={16} />}
          label="Machine Intelligence"
          accent="var(--info)"
          cols="sm:grid-cols-2 lg:grid-cols-3"
        >
          <Link to="/machines" className={STAT_CLS}>
            <KpiTile
              label="Avg Machine Health"
              value={`${data?.factory_health_summary.avg_health ?? 0}`}
              hint={`${data?.factory_health_summary.machines ?? 0} machines`}
              accent="var(--info)"
              {...metricTrend("health")}
            />
          </Link>
          <Link to="/work-orders" className={STAT_CLS}>
            <KpiTile
              label="Open Work Orders"
              value={k.open_work_orders ?? 0}
              accent="var(--warning)"
              hint="awaiting action"
              {...metricTrend("workorders")}
            />
          </Link>
          <Link to="/tickets" className={STAT_CLS}>
            <KpiTile
              label="Active Alerts"
              value={k.active_alerts ?? 0}
              accent="var(--danger)"
              hint="needs attention"
              {...metricTrend("alerts")}
            />
          </Link>
        </StatGroup>

        <StatGroup
          icon={<SlidersHorizontal size={16} />}
          label="Factory Intelligence"
          accent="var(--success)"
          cols="sm:grid-cols-2 lg:grid-cols-3"
        >
          <Link to="/quality" className={STAT_CLS}>
            <KpiTile
              label="OEE"
              value={`${((k.avg_oee ?? 0) * 100).toFixed(1)}%`}
              hint="overall effectiveness"
              accent="var(--success)"
              {...metricTrend("oee")}
            />
          </Link>
          <Link to="/quality" className={STAT_CLS}>
            <KpiTile
              label="Scrap Rate"
              value={`${((k.avg_scrap_rate ?? 0) * 100).toFixed(1)}%`}
              hint="of total output"
              accent="var(--danger)"
              {...metricTrend("scrap")}
            />
          </Link>
          <Link to="/analytics" className={STAT_CLS}>
            <KpiTile
              label="Throughput"
              value={k.throughput ?? 0}
              hint="units / shift"
              {...metricTrend("throughput")}
            />
          </Link>
        </StatGroup>

        <StatGroup
          icon={<PackageCheck size={16} />}
          label="Purchase Orders"
          accent="var(--warning)"
          cols="sm:grid-cols-2 lg:grid-cols-3"
        >
          <Link to="/order-tracker" className={STAT_CLS}>
            <KpiTile
              label="Open Purchase Orders"
              value={openPOs}
              accent="var(--info)"
              hint="in procurement"
              {...metricTrend("openpos")}
            />
          </Link>
          <Link to="/order-tracker" className={STAT_CLS}>
            <KpiTile
              label="Delayed Orders"
              value={k.delayed_orders ?? 0}
              accent="var(--danger)"
              hint="past due"
              {...metricTrend("delayedorders")}
            />
          </Link>
          <Link to="/supply-chain" className={STAT_CLS}>
            <KpiTile
              label="Inventory at Risk"
              value={k.inventory_below_threshold ?? 0}
              accent="var(--warning)"
              hint="below reorder point"
              {...metricTrend("inventoryrisk")}
            />
          </Link>
        </StatGroup>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="At-Risk Machines">
          <ul className="space-y-3">
            {data?.factory_health_summary.at_risk.map((m) => (
              <li key={m.code}>
                <Link
                  to="/machines"
                  aria-label={`Open ${m.code} in Machines`}
                  className="-mx-2 flex items-center justify-between rounded-md px-2 py-1.5 transition-colors hover:bg-accent"
                >
                  <span className="flex items-center gap-2">
                    <Gauge size={16} className="text-muted-foreground" />
                    {m.code}
                  </span>
                  <span className="flex items-center gap-2">
                    <span className={`font-semibold ${healthColor(m.health)}`}>
                      {m.health}
                    </span>
                    <ChevronRight size={15} className="text-muted-foreground" />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel
          title="Risk Alerts"
          action={
            <span
              className="rounded-full border px-2 py-0.5 text-xs font-medium"
              style={{
                borderColor: "var(--danger)",
                color: "var(--danger)",
                backgroundColor: "color-mix(in oklab, var(--danger) 12%, transparent)",
              }}
            >
              {k.active_alerts ?? 0} active
            </span>
          }
        >
          <ul className="space-y-3">
            {data?.risk_alerts.length === 0 && (
              <li className="text-sm text-muted-foreground">No active alerts.</li>
            )}
            {data?.risk_alerts.map((a) => (
              <li key={a.id}>
                <Link
                  to="/tickets"
                  aria-label="Open this alert in the Maintenance Alert Center"
                  className="-mx-2 flex items-start justify-between gap-3 rounded-md px-2 py-1.5 transition-colors hover:bg-accent"
                >
                  <span className="flex items-start gap-2 text-sm">
                    <AlertTriangle size={16} className="mt-0.5 text-warning" />
                    {a.message}
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <StatusBadge value={a.severity} />
                    <ChevronRight size={15} className="text-muted-foreground" />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  )
}

// A labeled cluster of related stats — icon chip + section name + a fading
// accent hairline, mirroring the sidebar grouping.
function StatGroup({
  icon,
  label,
  accent,
  cols,
  children,
}: {
  icon: ReactNode
  label: string
  accent: string
  cols: string
  children: ReactNode
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-3">
        <span
          className="flex size-7 items-center justify-center rounded-lg"
          style={{
            color: accent,
            backgroundColor: `color-mix(in oklab, ${accent} 14%, transparent)`,
          }}
        >
          {icon}
        </span>
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
        <span
          className="h-px flex-1 rounded"
          style={{
            backgroundImage: `linear-gradient(to right, color-mix(in oklab, ${accent} 45%, transparent), transparent)`,
          }}
        />
      </div>
      <div className={`grid gap-4 ${cols}`}>{children}</div>
    </section>
  )
}
