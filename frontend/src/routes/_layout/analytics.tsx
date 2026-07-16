import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Activity, RefreshCw } from "lucide-react"
import { useEffect, useState } from "react"
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import {
  BarTrend,
  HEX,
  healthColor,
  KpiTile,
  Loading,
  metricTrend,
  PageHeader,
  Panel,
} from "@/smartforge/components"
import type {
  CommandCenter,
  Machine,
  OeeMetric,
  Page,
} from "@/smartforge/types"

export const Route = createFileRoute("/_layout/analytics")({
  component: AnalyticsPage,
  head: () => ({ meta: [{ title: "Analytics - SmartForge" }] }),
})

// Routable stat tile wrapper (same affordance as the Command Center).
const STAT_CLS =
  "block rounded-xl outline-none transition hover:brightness-110 focus-visible:ring-2 focus-visible:ring-ring"

// Grafana-style refresh cadences. Default 1 minute; down to 1s, up to 1h.
const INTERVALS = [
  { label: "1s", ms: 1000 },
  { label: "30s", ms: 30000 },
  { label: "1m", ms: 60000 },
  { label: "1h", ms: 3600000 },
] as const

const MAX_POINTS = 60

interface Snapshot {
  t: string
  oee: number
  throughput: number
  health: number
  scrap: number
  downtime: number
  alerts: number
  wos: number
}

function AnalyticsPage() {
  const [intervalMs, setIntervalMs] = useState<number>(60000)
  const [history, setHistory] = useState<Snapshot[]>([])

  const cc = useQuery({
    queryKey: ["sf-command-center"],
    queryFn: () => sf.get<CommandCenter>("/command-center"),
    refetchInterval: intervalMs,
  })
  const oee = useQuery({
    queryKey: ["sf-oee"],
    queryFn: () => sf.get<Page<OeeMetric>>("/oee"),
    refetchInterval: intervalMs,
  })
  const machines = useQuery({
    queryKey: ["sf-machines-dash"],
    queryFn: () => sf.get<Page<Machine>>("/machines/"),
    refetchInterval: intervalMs,
  })

  // Build a rolling time-series from each successful poll (Grafana feel).
  useEffect(() => {
    const d = cc.data
    if (!d) return
    const k = d.kpis
    const point: Snapshot = {
      t: new Date().toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }),
      oee: +((k.avg_oee ?? 0) * 100).toFixed(1),
      throughput: Math.round(k.throughput ?? 0),
      health: +(d.factory_health_summary.avg_health ?? 0).toFixed(1),
      scrap: +((k.avg_scrap_rate ?? 0) * 100).toFixed(2),
      downtime: Math.round(k.unplanned_downtime_minutes ?? 0),
      alerts: k.active_alerts ?? 0,
      wos: k.open_work_orders ?? 0,
    }
    setHistory((h) => [...h.slice(-(MAX_POINTS - 1)), point])
  }, [cc.data])

  const k = cc.data?.kpis ?? {}
  const oeeRows = oee.data?.data ?? []
  const mach = machines.data?.data ?? []

  // OEE by shift (averaged when multiple lines share a shift).
  const byShift = Object.values(
    oeeRows.reduce<Record<string, { shift: string; sum: number; n: number }>>(
      (acc, r) => {
        acc[r.shift] ??= { shift: r.shift, sum: 0, n: 0 }
        const s = acc[r.shift]
        s.sum += r.oee * 100
        s.n += 1
        return acc
      },
      {},
    ),
  ).map((s) => ({ shift: s.shift, oee: +(s.sum / s.n).toFixed(1) }))

  const avg = (sel: (o: OeeMetric) => number) =>
    oeeRows.length
      ? oeeRows.reduce((a, o) => a + sel(o), 0) / oeeRows.length
      : 0

  const dist = {
    healthy: mach.filter((m) => (m.health_score ?? 0) >= 80).length,
    atRisk: mach.filter(
      (m) => (m.health_score ?? 0) >= 60 && (m.health_score ?? 0) < 80,
    ).length,
    critical: mach.filter((m) => (m.health_score ?? 0) < 60).length,
  }

  const lastUpdated = cc.dataUpdatedAt
    ? new Date(cc.dataUpdatedAt).toLocaleTimeString()
    : "—"

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Analytics"
        description="Executive operations intelligence · live global KPIs across the plant."
        actions={
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Activity size={13} className="text-success" />
              updated {lastUpdated}
            </span>
            <div className="flex items-center gap-1 rounded-lg border bg-card p-1">
              <RefreshCw size={13} className="ml-1 text-muted-foreground" />
              {INTERVALS.map((opt) => (
                <button
                  key={opt.ms}
                  type="button"
                  onClick={() => setIntervalMs(opt.ms)}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                    intervalMs === opt.ms
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent",
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        }
      />

      {cc.isLoading && <Loading label="Loading factory intelligence…" />}

      {/* Executive KPI band — each tile links to its source page. */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-4">
        <Link to="/quality" className={STAT_CLS}>
          <KpiTile
            label="Overall OEE"
            value={`${((k.avg_oee ?? 0) * 100).toFixed(1)}%`}
            hint="overall effectiveness"
            accent={HEX.info}
            {...metricTrend("oee")}
          />
        </Link>
        <Link to="/machines" className={STAT_CLS}>
          <KpiTile
            label="Avg Machine Health"
            value={`${cc.data?.factory_health_summary.avg_health ?? 0}`}
            hint={`${cc.data?.factory_health_summary.machines ?? 0} machines online`}
            accent={HEX.success}
            {...metricTrend("health")}
          />
        </Link>
        <Link to="/quality" className={STAT_CLS}>
          <KpiTile
            label="Throughput / day"
            value={Math.round(k.throughput ?? 0)}
            hint="units produced / day"
            {...metricTrend("throughput")}
          />
        </Link>
        <Link to="/quality" className={STAT_CLS}>
          <KpiTile
            label="Scrap Rate"
            value={`${((k.avg_scrap_rate ?? 0) * 100).toFixed(2)}%`}
            hint="of total output"
            accent={HEX.warning}
            {...metricTrend("scrap")}
          />
        </Link>
        <Link to="/work-orders" className={STAT_CLS}>
          <KpiTile
            label="Open Work Orders"
            value={k.open_work_orders ?? 0}
            hint="awaiting action"
            accent={HEX.warning}
            {...metricTrend("workorders")}
          />
        </Link>
        <Link to="/tickets" className={STAT_CLS}>
          <KpiTile
            label="Active Alerts"
            value={k.active_alerts ?? 0}
            hint="needs attention"
            accent={HEX.danger}
            {...metricTrend("alerts")}
          />
        </Link>
        <Link to="/incidents" className={STAT_CLS}>
          <KpiTile
            label="Unplanned Downtime"
            value={`${k.unplanned_downtime_minutes ?? 0}m`}
            hint="this period"
            accent={HEX.danger}
            {...metricTrend("downtime")}
          />
        </Link>
        <Link to="/order-tracker" className={STAT_CLS}>
          <KpiTile
            label="Delayed Orders"
            value={k.delayed_orders ?? 0}
            hint="past due"
            accent={HEX.danger}
            {...metricTrend("delayedorders")}
          />
        </Link>
      </div>

      {/* Real-time time-series (built from the polling cadence) */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="OEE Trend (%)">
          <TimeSeries
            data={history}
            dataKey="oee"
            color={HEX.info}
            domain={[0, 100]}
          />
        </Panel>
        <Panel title="Throughput (units)">
          <TimeSeries data={history} dataKey="throughput" color={HEX.success} />
        </Panel>
        <Panel title="Avg Machine Health">
          <TimeSeries
            data={history}
            dataKey="health"
            color="var(--primary)"
            domain={[0, 100]}
          />
        </Panel>
        <Panel title="Alerts & Open Work Orders">
          <ResponsiveContainer width="100%" height={150}>
            <LineChart data={history}>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="var(--border)"
                vertical={false}
              />
              <XAxis
                dataKey="t"
                stroke="var(--muted-foreground)"
                fontSize={10}
                minTickGap={28}
              />
              <YAxis
                stroke="var(--muted-foreground)"
                fontSize={10}
                allowDecimals={false}
                width={28}
              />
              <Tooltip
                contentStyle={{
                  background: "var(--popover)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Line
                type="monotone"
                dataKey="alerts"
                stroke={HEX.danger}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="wos"
                stroke={HEX.warning}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
          <div className="mt-2 flex gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <i
                className="size-2 rounded-full"
                style={{ background: HEX.danger }}
              />{" "}
              Active alerts
            </span>
            <span className="flex items-center gap-1">
              <i
                className="size-2 rounded-full"
                style={{ background: HEX.warning }}
              />{" "}
              Open work orders
            </span>
          </div>
        </Panel>
      </div>

      {/* Breakdown row */}
      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="OEE by Shift (%)">
          {byShift.length > 0 ? (
            <BarTrend
              data={byShift}
              dataKey="oee"
              xKey="shift"
              color={HEX.info}
              height={200}
            />
          ) : (
            <p className="text-sm text-muted-foreground">No OEE records.</p>
          )}
        </Panel>

        <Panel title="OEE Components">
          {/* each component links to Quality (its source). */}
          <div className="space-y-3">
            <Link to="/quality" className={STAT_CLS}>
              <MeterRow
                label="Availability"
                value={avg((o) => o.availability) * 100}
                color={HEX.success}
              />
            </Link>
            <Link to="/quality" className={STAT_CLS}>
              <MeterRow
                label="Performance"
                value={avg((o) => o.performance) * 100}
                color={HEX.info}
              />
            </Link>
            <Link to="/quality" className={STAT_CLS}>
              <MeterRow
                label="Quality"
                value={avg((o) => o.quality) * 100}
                color="var(--primary)"
              />
            </Link>
            <Link to="/quality" className={STAT_CLS}>
              <MeterRow
                label="Rework rate"
                value={avg((o) => o.rework_rate) * 100}
                color={HEX.warning}
              />
            </Link>
          </div>
        </Panel>

        <Panel title="Fleet Health Distribution">
          <div className="grid grid-cols-3 gap-3 text-center">
            <Link to="/machines" className={STAT_CLS}>
              <DistTile
                label="Healthy"
                value={dist.healthy}
                color={HEX.success}
              />
            </Link>
            <Link to="/machines" className={STAT_CLS}>
              <DistTile
                label="At risk"
                value={dist.atRisk}
                color={HEX.warning}
              />
            </Link>
            <Link to="/machines" className={STAT_CLS}>
              <DistTile
                label="Critical"
                value={dist.critical}
                color={HEX.danger}
              />
            </Link>
          </div>
          <ul className="mt-4 space-y-1">
            {cc.data?.factory_health_summary.at_risk.map((m) => (
              <li key={m.code}>
                <Link
                  to="/machines"
                  className="-mx-2 flex items-center justify-between rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent"
                >
                  <span>{m.code}</span>
                  <span className={`font-semibold ${healthColor(m.health)}`}>
                    {m.health}
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

function TimeSeries({
  data,
  dataKey,
  color,
  domain,
}: {
  data: Snapshot[]
  dataKey: keyof Snapshot
  color: string
  domain?: [number, number]
}) {
  if (data.length === 0)
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        Collecting live samples…
      </p>
    )
  return (
    <ResponsiveContainer width="100%" height={150}>
      <AreaChart data={data}>
        <defs>
          <linearGradient
            id={`g-${String(dataKey)}`}
            x1="0"
            y1="0"
            x2="0"
            y2="1"
          >
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="var(--border)"
          vertical={false}
        />
        <XAxis
          dataKey="t"
          stroke="var(--muted-foreground)"
          fontSize={10}
          minTickGap={28}
        />
        <YAxis
          stroke="var(--muted-foreground)"
          fontSize={10}
          width={32}
          domain={domain ?? ["auto", "auto"]}
        />
        <Tooltip
          contentStyle={{
            background: "var(--popover)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            fontSize: 12,
          }}
        />
        <Area
          type="monotone"
          dataKey={dataKey}
          stroke={color}
          strokeWidth={2}
          fill={`url(#g-${String(dataKey)})`}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

function MeterRow({
  label,
  value,
  color,
}: {
  label: string
  value: number
  color: string
}) {
  const pct = Math.max(0, Math.min(100, value))
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-semibold tabular-nums">{pct.toFixed(1)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
    </div>
  )
}

function DistTile({
  label,
  value,
  color,
}: {
  label: string
  value: number
  color: string
}) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <div className="text-2xl font-semibold tabular-nums" style={{ color }}>
        {value}
      </div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  )
}
