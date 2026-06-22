import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import type { ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"

// Standardized page header used by every app/portal page: a uniform H1
// (text-2xl font-semibold — preserves getByRole("heading") in tests), an
// optional muted description, an optional leading icon, and a right-aligned
// actions slot. Keeps headers consistent page-by-page.
export function PageHeader({
  title,
  description,
  icon,
  actions,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  icon?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-3", className)}>
      <div className="min-w-0">
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          {icon}
          {title}
        </h1>
        {description && (
          <p className="mt-1 text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

// Friendly display name for the signed-in user: full name when set, otherwise a
// prettified email local-part (john.doe@… → "John Doe"). Used for greetings and
// action sign-offs.
export function userDisplayName(
  user?: { full_name?: string | null; email?: string | null } | null,
): string {
  if (!user) return "there"
  const name = user.full_name?.trim()
  if (name) return name
  const local = (user.email ?? "").split("@")[0] ?? ""
  if (!local) return "there"
  return local.replace(/[._-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-12 text-sm text-muted-foreground">
      <span className="h-3 w-3 animate-ping rounded-full bg-primary" />
      {label}
    </div>
  )
}

/**
 * Literal hex values for the semantic status tokens — required where CSS
 * variables can't reach (recharts, the WebGL scene). Kept in sync with the
 * `--success/--warning/--danger/--info` tokens defined in index.css.
 */
export const HEX = {
  success: "#10b981",
  warning: "#f59e0b",
  danger: "#ef4444",
  info: "#38bdf8",
} as const

// Score → semantic health band (≥80 healthy, ≥60 at-risk, else critical).
const HEALTHY = 80
const AT_RISK = 60

export function healthColor(score: number): string {
  if (score >= HEALTHY) return "text-success"
  if (score >= AT_RISK) return "text-warning"
  return "text-danger"
}

export function healthHex(score: number): string {
  if (score >= HEALTHY) return HEX.success
  if (score >= AT_RISK) return HEX.warning
  return HEX.danger
}

// Deterministic 24-point "last 24h" trend for a KPI tile. `good` says which
// direction is positive (e.g. scrap/downtime/alerts improve when going DOWN),
// which decides the green/red color. Stable per `seed` so it doesn't jump.
export function makeTrendSeries(
  seed: string,
  good: "up" | "down" = "up",
): { data: number[]; color: string } {
  const h = hashStr(seed)
  const n = 24
  const slope = ((h % 7) - 3) / 3 // -1..1
  const data = Array.from({ length: n }, (_, i) => {
    const base = 50 + slope * (i / (n - 1)) * 26
    const noise = Math.sin(i * 1.4 + (h % 11)) * 3 + ((h >> (i % 8)) % 5)
    return base + noise
  })
  const rising = data[n - 1] >= data[0]
  const improving = good === "up" ? rising : !rising
  return { data, color: improving ? HEX.success : HEX.danger }
}

// Canonical per-metric trend so the SAME metric renders an IDENTICAL sparkline
// (shape + color) everywhere it appears — Command Center, Analytics and the
// per-page dashboards stay perfectly consistent. "Good" metrics trend green,
// "bad" ones red. (Open Work Orders + Throughput are intentionally green.)
const METRIC_TREND: Record<string, { seed: string; color: string }> = {
  oee: { seed: "mt-oee", color: HEX.success },
  health: { seed: "mt-health", color: HEX.success },
  throughput: { seed: "mt-throughput", color: HEX.success },
  workorders: { seed: "mt-workorders", color: HEX.success },
  scrap: { seed: "mt-scrap", color: HEX.danger },
  defects: { seed: "mt-defects", color: HEX.danger },
  scrapcost: { seed: "mt-scrapcost", color: HEX.danger },
  alerts: { seed: "mt-alerts", color: HEX.danger },
  downtime: { seed: "mt-downtime", color: HEX.danger },
  delayedorders: { seed: "mt-delayed", color: HEX.danger },
  openpos: { seed: "mt-openpos", color: HEX.success },
  inventoryrisk: { seed: "mt-invrisk", color: HEX.danger },
  // order tracker
  pocount: { seed: "mt-pocount", color: HEX.success },
  povalue: { seed: "mt-povalue", color: HEX.success },
  poopen: { seed: "mt-poopen", color: HEX.success },
  poreceived: { seed: "mt-poreceived", color: HEX.success },
  poready: { seed: "mt-poready", color: HEX.success },
  // supply chain
  skus: { seed: "mt-skus", color: HEX.success },
  belowthreshold: { seed: "mt-below", color: HEX.danger },
  delayedsuppliers: { seed: "mt-delsup", color: HEX.danger },
  // incidents
  incidents: { seed: "mt-incidents", color: HEX.danger },
  costimpact: { seed: "mt-costimpact", color: HEX.danger },
}

export function metricTrend(metric: string): { trend: number[]; trendColor: string } {
  const m = METRIC_TREND[metric] ?? { seed: metric, color: HEX.success }
  return { trend: makeTrendSeries(m.seed).data, trendColor: m.color }
}

function hashStr(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h)
}

// Lightweight inline-SVG sparkline used as a faint background behind KPI values.
function Sparkline({ data, color }: { data: number[]; color: string }) {
  if (data.length < 2) return null
  const w = 100
  const hgt = 40
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const pts = data
    .map((v, i) => `${(i / (data.length - 1)) * w},${hgt - ((v - min) / range) * hgt}`)
    .join(" ")
  return (
    <svg
      viewBox={`0 0 ${w} ${hgt}`}
      preserveAspectRatio="none"
      aria-hidden
      className="pointer-events-none absolute inset-x-0 bottom-0 z-0 h-2/3 w-full opacity-30"
    >
      <polygon points={`0,${hgt} ${pts} ${w},${hgt}`} fill={color} fillOpacity={0.12} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

export function KpiTile({
  label,
  value,
  hint,
  accent,
  trend,
  trendColor,
}: {
  label: string
  value: string | number
  hint?: string
  accent?: string
  /** Optional 24h series rendered as a faint background sparkline. */
  trend?: number[]
  trendColor?: string
}) {
  // Borderless: status color is conveyed purely by a subtle gradient wash of
  // the accent over the card (no outline).
  const a = accent ?? "var(--primary)"
  return (
    <Card
      className="relative overflow-hidden transition-all hover:shadow-[var(--shadow-glass)]"
      style={{
        borderColor: "transparent",
        backgroundImage: `linear-gradient(155deg, color-mix(in oklab, ${a} 16%, var(--card)) 0%, var(--card) 72%)`,
      }}
    >
      {trend && trend.length > 1 && (
        <Sparkline data={trend} color={trendColor ?? HEX.success} />
      )}
      <CardHeader className="relative z-10 pb-1">
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent className="relative z-10">
        <div className="text-3xl font-semibold tabular-nums">{value}</div>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  )
}

const SEVERITY: Record<string, string> = {
  critical: "bg-danger/15 text-danger border-danger/30",
  high: "bg-danger/15 text-danger border-danger/30",
  medium: "bg-warning/15 text-warning border-warning/30",
  low: "bg-info/15 text-info border-info/30",
}
const STATUS: Record<string, string> = {
  running: "bg-success/15 text-success border-success/30",
  idle: "bg-muted text-muted-foreground border-border",
  fault: "bg-danger/15 text-danger border-danger/30",
  maintenance: "bg-warning/15 text-warning border-warning/30",
  offline: "bg-muted text-muted-foreground border-border",
}

export function StatusBadge({ value }: { value: string }) {
  const cls = SEVERITY[value] ?? STATUS[value] ?? "bg-muted text-muted-foreground"
  return (
    <Badge variant="outline" className={cn("capitalize", cls)}>
      {value}
    </Badge>
  )
}

// Unified order/quote/PO status → color (used by Quotes, Order Tracker, Supply
// Chain): Approved/Closed = green, Open = blue, In-Review = yellow, Denied = red.
export function orderStatusColor(status: string): string {
  const s = (status || "").toLowerCase().replace(/[\s_-]/g, "")
  if (["approved", "closed", "received", "complete", "completed", "done", "fulfilled"].includes(s))
    return HEX.success
  if (["open", "issued", "active", "shipped"].includes(s)) return HEX.info
  if (["denied", "rejected", "cancelled", "canceled", "failed"].includes(s)) return HEX.danger
  if (["inreview", "review", "pending", "intake", "draft", "quoting", "quoted", "new"].includes(s))
    return HEX.warning
  return HEX.info
}

// A pill-style status bubble (colored outline + low-opacity wash). Inline border
// color survives the global borderless rule.
export function OrderStatusBadge({ status, label }: { status: string; label?: string }) {
  const c = orderStatusColor(status)
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize"
      style={{
        color: c,
        border: `1px solid ${c}`,
        backgroundColor: `color-mix(in oklab, ${c} 16%, transparent)`,
      }}
    >
      {(label ?? status).replace(/[_-]/g, " ")}
    </span>
  )
}

export function Panel({
  title,
  action,
  children,
  className,
}: {
  title: string
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">{title}</CardTitle>
        {action}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

export function MiniArea({
  data,
  dataKey,
  color = "var(--primary)",
}: {
  data: Array<Record<string, number | string>>
  dataKey: string
  color?: string
}) {
  return (
    <ResponsiveContainer width="100%" height={60}>
      <AreaChart data={data} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
        <Area
          type="monotone"
          dataKey={dataKey}
          stroke={color}
          fill={color}
          fillOpacity={0.15}
          strokeWidth={2}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

export function BarTrend({
  data,
  dataKey,
  xKey,
  color = "var(--primary)",
  height = 240,
}: {
  data: Array<Record<string, number | string>>
  dataKey: string
  xKey: string
  color?: string
  height?: number
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey={xKey} stroke="var(--muted-foreground)" fontSize={11} />
        <YAxis stroke="var(--muted-foreground)" fontSize={11} />
        <Tooltip
          contentStyle={{
            background: "var(--popover)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            fontSize: 12,
          }}
        />
        <Bar dataKey={dataKey} fill={color} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}
