import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Database, Download, LayoutGrid, Table2, Upload } from "lucide-react"
import { useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import { POLL } from "@/smartforge/constants"
import { HEX, Loading, PageHeader } from "@/smartforge/components"
import { Gauge, Heartbeat } from "@/smartforge/widgets"

export const Route = createFileRoute("/_layout/datasources")({
  component: DatasourcesPage,
  head: () => ({ meta: [{ title: "Datasources - SmartForge" }] }),
})

type ColType = "text" | "num" | "money" | "pct" | "bool" | "date"
interface Column {
  key: string
  label: string
  type?: ColType
}
type Row = Record<string, unknown>
interface GaugeMetric {
  label: string
  value: number
  max: number
  suffix?: "%" | "$" | "d" | ""
}
interface Datasource {
  key: string
  label: string
  endpoint: string
  columns: Column[]
  metrics: (rows: Row[]) => GaugeMetric[]
}

/* ----------------------------------------------------------- aggregations */

const num = (v: unknown) => (typeof v === "number" ? v : Number(v) || 0)
const avg = (rows: Row[], k: string) =>
  rows.length ? rows.reduce((a, r) => a + num(r[k]), 0) / rows.length : 0
const maxOf = (rows: Row[], k: string) =>
  rows.reduce((m, r) => Math.max(m, num(r[k])), 0)
const countWhere = (rows: Row[], fn: (r: Row) => boolean) => rows.filter(fn).length

// Live, read-only production tables exposed for inspection — each with the
// gauges that summarize it (all computed from the real rows).
const DATASOURCES: Datasource[] = [
  {
    key: "machines",
    label: "Machines",
    endpoint: "/machines/",
    columns: [
      { key: "code", label: "Code" },
      { key: "name", label: "Name" },
      { key: "machine_type", label: "Type" },
      { key: "status", label: "Status" },
      { key: "health_score", label: "Health", type: "num" },
      { key: "runtime_hours", label: "Runtime (h)", type: "num" },
      { key: "last_fault_code", label: "Fault" },
    ],
    metrics: (r) => [
      { label: "Avg Health", value: avg(r, "health_score"), max: 100 },
      { label: "Running", value: countWhere(r, (x) => x.status === "running"), max: r.length || 1 },
      { label: "Faults", value: countWhere(r, (x) => !!x.last_fault_code), max: r.length || 1 },
    ],
  },
  {
    key: "alerts",
    label: "Alerts",
    endpoint: "/alerts/",
    columns: [
      { key: "severity", label: "Severity" },
      { key: "rule", label: "Rule" },
      { key: "message", label: "Message" },
      { key: "status", label: "Status" },
      { key: "created_at", label: "Created", type: "date" },
    ],
    metrics: (r) => [
      { label: "Active", value: countWhere(r, (x) => x.status === "active"), max: r.length || 1 },
      {
        label: "Critical",
        value: countWhere(r, (x) => x.severity === "critical" || x.severity === "high"),
        max: r.length || 1,
      },
      { label: "Resolved", value: countWhere(r, (x) => x.status === "resolved"), max: r.length || 1 },
    ],
  },
  {
    key: "work-orders",
    label: "Work Orders",
    endpoint: "/work-orders/",
    columns: [
      { key: "fault_type", label: "Fault Type" },
      { key: "severity", label: "Severity" },
      { key: "recommended_task", label: "Recommended Task" },
      { key: "required_skill", label: "Skill" },
      { key: "priority", label: "Priority", type: "num" },
      { key: "status", label: "Status" },
      { key: "fiix_sync_state", label: "Fiix Sync" },
    ],
    metrics: (r) => [
      { label: "Open", value: countWhere(r, (x) => x.status !== "completed"), max: r.length || 1 },
      {
        label: "High sev",
        value: countWhere(r, (x) => x.severity === "high" || x.severity === "critical"),
        max: r.length || 1,
      },
      { label: "Done", value: countWhere(r, (x) => x.status === "completed"), max: r.length || 1 },
    ],
  },
  {
    key: "oee",
    label: "OEE Metrics",
    endpoint: "/oee",
    columns: [
      { key: "shift", label: "Shift" },
      { key: "availability", label: "Availability", type: "pct" },
      { key: "performance", label: "Performance", type: "pct" },
      { key: "quality", label: "Quality", type: "pct" },
      { key: "oee", label: "OEE", type: "pct" },
      { key: "scrap_rate", label: "Scrap", type: "pct" },
      { key: "throughput", label: "Throughput", type: "num" },
    ],
    metrics: (r) => [
      { label: "OEE", value: avg(r, "oee") * 100, max: 100, suffix: "%" },
      { label: "Availability", value: avg(r, "availability") * 100, max: 100, suffix: "%" },
      { label: "Quality", value: avg(r, "quality") * 100, max: 100, suffix: "%" },
    ],
  },
  {
    key: "defects",
    label: "Defects",
    endpoint: "/defects",
    columns: [
      { key: "defect_type", label: "Defect Type" },
      { key: "part_id", label: "Part" },
      { key: "scrap_cost", label: "Scrap Cost", type: "money" },
      { key: "is_scrap", label: "Scrap?", type: "bool" },
      { key: "created_at", label: "Created", type: "date" },
    ],
    metrics: (r) => {
      const scrap = countWhere(r, (x) => !!x.is_scrap)
      return [
        { label: "Scrap", value: scrap, max: r.length || 1 },
        { label: "Clean", value: r.length - scrap, max: r.length || 1 },
        { label: "Scrap rate", value: r.length ? (scrap / r.length) * 100 : 0, max: 100, suffix: "%" },
      ]
    },
  },
  {
    key: "inventory",
    label: "Inventory",
    endpoint: "/inventory",
    columns: [
      { key: "sku", label: "SKU" },
      { key: "name", label: "Name" },
      { key: "quantity", label: "Qty", type: "num" },
      { key: "reorder_threshold", label: "Reorder At", type: "num" },
      { key: "below_threshold", label: "Below?", type: "bool" },
    ],
    metrics: (r) => {
      const below = countWhere(r, (x) => !!x.below_threshold)
      return [
        { label: "Low stock", value: below, max: r.length || 1 },
        { label: "Healthy", value: r.length - below, max: r.length || 1 },
        { label: "Avg qty", value: avg(r, "quantity"), max: maxOf(r, "quantity") || 1 },
      ]
    },
  },
  {
    key: "purchase-orders",
    label: "Purchase Orders",
    endpoint: "/purchase-orders",
    columns: [
      { key: "po_number", label: "PO #" },
      { key: "amount", label: "Amount", type: "money" },
      { key: "status", label: "Status" },
      { key: "shop_floor_ready", label: "Ready?", type: "bool" },
    ],
    metrics: (r) => [
      { label: "Open", value: countWhere(r, (x) => x.status === "open"), max: r.length || 1 },
      { label: "Received", value: countWhere(r, (x) => x.status === "received"), max: r.length || 1 },
      { label: "Ready", value: countWhere(r, (x) => !!x.shop_floor_ready), max: r.length || 1 },
    ],
  },
  {
    key: "order-tracker",
    label: "Order Tracker",
    endpoint: "/order-tracker",
    columns: [
      { key: "po_number", label: "PO #" },
      { key: "order_number", label: "Order" },
      { key: "customer", label: "Customer" },
      { key: "part_type", label: "Part" },
      { key: "quantity", label: "Qty", type: "num" },
      { key: "supplier", label: "Supplier" },
      { key: "status", label: "Status" },
      { key: "amount", label: "Total", type: "money" },
      { key: "shop_floor_ready", label: "Ready?", type: "bool" },
    ],
    metrics: (r) => {
      const total = r.reduce((a, x) => a + num(x.amount), 0)
      return [
        { label: "Active POs", value: r.length, max: r.length || 1 },
        { label: "Open", value: countWhere(r, (x) => x.status === "open"), max: r.length || 1 },
        { label: "Total Value", value: total, max: total || 1, suffix: "$" },
      ]
    },
  },
  {
    key: "suppliers",
    label: "Suppliers",
    endpoint: "/suppliers",
    columns: [
      { key: "name", label: "Name" },
      { key: "status", label: "Status" },
      { key: "lead_time_days", label: "Lead (days)", type: "num" },
    ],
    metrics: (r) => [
      { label: "Healthy", value: countWhere(r, (x) => x.status === "ok"), max: r.length || 1 },
      { label: "At risk", value: countWhere(r, (x) => x.status !== "ok"), max: r.length || 1 },
      { label: "Avg lead", value: avg(r, "lead_time_days"), max: 30, suffix: "d" },
    ],
  },
  {
    key: "incidents",
    label: "Incidents",
    endpoint: "/incidents/",
    columns: [
      { key: "title", label: "Title" },
      { key: "severity", label: "Severity" },
      { key: "downtime_minutes", label: "Downtime (m)", type: "num" },
      { key: "estimated_cost", label: "Cost", type: "money" },
      { key: "delayed_orders", label: "Delayed", type: "num" },
      { key: "resolved", label: "Resolved?", type: "bool" },
    ],
    metrics: (r) => [
      { label: "Open", value: countWhere(r, (x) => !x.resolved), max: r.length || 1 },
      { label: "Resolved", value: countWhere(r, (x) => !!x.resolved), max: r.length || 1 },
      { label: "Avg cost", value: avg(r, "estimated_cost"), max: maxOf(r, "estimated_cost") || 1, suffix: "$" },
    ],
  },
  {
    key: "recommendations",
    label: "Recommendations",
    endpoint: "/recommendations",
    columns: [
      { key: "category", label: "Category" },
      { key: "title", label: "Title" },
      { key: "confidence", label: "Confidence", type: "pct" },
      { key: "status", label: "Status" },
      { key: "outcome_impact", label: "Impact", type: "num" },
    ],
    metrics: (r) => [
      { label: "Pending", value: countWhere(r, (x) => x.status === "pending"), max: r.length || 1 },
      { label: "Accepted", value: countWhere(r, (x) => x.status === "accepted"), max: r.length || 1 },
      { label: "Confidence", value: avg(r, "confidence") * 100, max: 100, suffix: "%" },
    ],
  },
  {
    key: "tickets",
    label: "Maintenance Tickets",
    endpoint: "/tickets/",
    columns: [
      { key: "code", label: "Ticket" },
      { key: "title", label: "Title" },
      { key: "severity", label: "Severity" },
      { key: "status", label: "Status" },
      { key: "machine_code", label: "Machine" },
      { key: "acknowledged_by", label: "Ack By" },
      { key: "created_at", label: "Created", type: "date" },
    ],
    metrics: (r) => [
      { label: "Open", value: countWhere(r, (x) => x.status === "open"), max: r.length || 1 },
      {
        label: "Acknowledged",
        value: countWhere(r, (x) => x.status === "acknowledged"),
        max: r.length || 1,
      },
      {
        label: "Critical",
        value: countWhere(r, (x) => x.severity === "critical"),
        max: r.length || 1,
      },
    ],
  },
  {
    key: "sops",
    label: "SOPs",
    endpoint: "/sops/",
    columns: [
      { key: "code", label: "Code" },
      { key: "title", label: "Title" },
      { key: "category", label: "Category" },
      { key: "entity_type", label: "Entity" },
      { key: "revision", label: "Rev" },
      { key: "summary", label: "Summary" },
    ],
    metrics: (r) => [
      { label: "Total SOPs", value: r.length, max: r.length || 1 },
      {
        label: "Maintenance",
        value: countWhere(r, (x) => x.category === "maintenance"),
        max: r.length || 1,
      },
      {
        label: "Machine-level",
        value: countWhere(r, (x) => x.entity_type === "machine"),
        max: r.length || 1,
      },
    ],
  },
  {
    key: "customer-orders",
    label: "Customer Orders",
    endpoint: "/datasources/table/customer_orders",
    columns: [
      { key: "order_number", label: "Order" },
      { key: "part_type", label: "Part" },
      { key: "quantity", label: "Qty", type: "num" },
      { key: "stage", label: "Stage" },
      { key: "delayed", label: "Delayed?", type: "bool" },
      { key: "created_at", label: "Created", type: "date" },
    ],
    metrics: (r) => [
      { label: "Orders", value: r.length, max: r.length || 1 },
      { label: "Delayed", value: countWhere(r, (x) => !!x.delayed), max: r.length || 1 },
      { label: "Shipped", value: countWhere(r, (x) => x.stage === "shipped"), max: r.length || 1 },
    ],
  },
  {
    key: "customers",
    label: "Customers",
    endpoint: "/datasources/table/customers",
    columns: [
      { key: "name", label: "Name" },
      { key: "contact_email", label: "Contact" },
      { key: "created_at", label: "Onboarded", type: "date" },
    ],
    metrics: (r) => [{ label: "Accounts", value: r.length, max: r.length || 1 }],
  },
  {
    key: "jobs",
    label: "Jobs",
    endpoint: "/datasources/table/jobs",
    columns: [
      { key: "customer", label: "Customer" },
      { key: "part_type", label: "Part" },
      { key: "quantity", label: "Qty", type: "num" },
      { key: "priority", label: "Priority", type: "num" },
      { key: "status", label: "Status" },
    ],
    metrics: (r) => [
      { label: "Jobs", value: r.length, max: r.length || 1 },
      { label: "Scheduled", value: countWhere(r, (x) => x.status === "scheduled"), max: r.length || 1 },
      { label: "In prod", value: countWhere(r, (x) => x.status === "in_production"), max: r.length || 1 },
    ],
  },
  {
    key: "production-runs",
    label: "Production Runs",
    endpoint: "/datasources/table/production_runs",
    columns: [
      { key: "shift", label: "Shift" },
      { key: "planned_units", label: "Planned", type: "num" },
      { key: "actual_units", label: "Actual", type: "num" },
      { key: "scrap_units", label: "Scrap", type: "num" },
      { key: "downtime_minutes", label: "Downtime (m)", type: "num" },
    ],
    metrics: (r) => [
      { label: "Runs", value: r.length, max: r.length || 1 },
      { label: "Avg actual", value: avg(r, "actual_units"), max: maxOf(r, "planned_units") || 1 },
      { label: "Avg downtime", value: avg(r, "downtime_minutes"), max: maxOf(r, "downtime_minutes") || 1 },
    ],
  },
  {
    key: "inspections",
    label: "Inspections",
    endpoint: "/datasources/table/inspections",
    columns: [
      { key: "part_id", label: "Part" },
      { key: "defect_detected", label: "Defect?", type: "bool" },
      { key: "defect_type", label: "Type" },
      { key: "confidence", label: "Confidence", type: "pct" },
      { key: "created_at", label: "Inspected", type: "date" },
    ],
    metrics: (r) => [
      { label: "Inspected", value: r.length, max: r.length || 1 },
      { label: "Defects", value: countWhere(r, (x) => !!x.defect_detected), max: r.length || 1 },
      { label: "Avg conf", value: avg(r, "confidence") * 100, max: 100, suffix: "%" },
    ],
  },
  {
    key: "machine-configs",
    label: "Machine Configurations",
    endpoint: "/datasources/table/machine_configurations",
    columns: [
      { key: "version", label: "Ver", type: "num" },
      { key: "is_current", label: "Current?", type: "bool" },
      { key: "is_recommended", label: "Recommended?", type: "bool" },
      { key: "speed", label: "Speed", type: "num" },
      { key: "temperature", label: "Temp", type: "num" },
      { key: "pressure", label: "Pressure", type: "num" },
    ],
    metrics: (r) => [
      { label: "Configs", value: r.length, max: r.length || 1 },
      { label: "Current", value: countWhere(r, (x) => !!x.is_current), max: r.length || 1 },
      { label: "Recommended", value: countWhere(r, (x) => !!x.is_recommended), max: r.length || 1 },
    ],
  },
  {
    key: "escalations",
    label: "Escalations",
    endpoint: "/datasources/table/escalations",
    columns: [
      { key: "status", label: "Status" },
      { key: "ai_confidence", label: "AI Conf", type: "pct" },
      { key: "assigned_team", label: "Team" },
      { key: "created_at", label: "Opened", type: "date" },
    ],
    metrics: (r) => [
      { label: "Total", value: r.length, max: r.length || 1 },
      { label: "Open", value: countWhere(r, (x) => x.status === "open"), max: r.length || 1 },
      { label: "Resolved", value: countWhere(r, (x) => x.status === "resolved"), max: r.length || 1 },
    ],
  },
  {
    key: "knowledge-docs",
    label: "Knowledge Documents",
    endpoint: "/datasources/table/knowledge_documents",
    columns: [
      { key: "title", label: "Title" },
      { key: "kind", label: "Kind" },
      { key: "tags", label: "Tags" },
      { key: "created_at", label: "Created", type: "date" },
    ],
    metrics: (r) => [
      { label: "Docs", value: r.length, max: r.length || 1 },
      { label: "SOPs", value: countWhere(r, (x) => x.kind === "sop"), max: r.length || 1 },
      { label: "Troubleshooting", value: countWhere(r, (x) => x.kind === "troubleshooting"), max: r.length || 1 },
    ],
  },
  {
    key: "audit-logs",
    label: "Audit Log",
    endpoint: "/datasources/table/audit_logs",
    columns: [
      { key: "actor_email", label: "Actor" },
      { key: "action", label: "Action" },
      { key: "entity_type", label: "Entity" },
      { key: "created_at", label: "When", type: "date" },
    ],
    metrics: (r) => [{ label: "Events", value: r.length, max: r.length || 1 }],
  },
]

function formatCell(value: unknown, type?: ColType) {
  if (value === null || value === undefined || value === "") return "—"
  const n = Number(value)
  switch (type) {
    case "money":
      return Number.isFinite(n) ? `$${n.toLocaleString()}` : String(value)
    case "pct":
      return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : String(value)
    case "num":
      return Number.isFinite(n) ? n.toLocaleString() : String(value)
    case "date": {
      const d = new Date(String(value))
      return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString()
    }
    case "bool":
      return value ? "Yes" : "No"
    default:
      return String(value)
  }
}

/* ---------------------------------------------------------- shared widgets */

function DataTable({ columns, rows }: { columns: Column[]; rows: Row[] }) {
  return (
    <table className="w-full border-collapse text-sm">
      <thead className="sticky top-0 z-10 bg-muted/95 backdrop-blur">
        <tr>
          <th className="w-10 border-b border-r px-2 py-2 text-right text-xs font-medium text-muted-foreground">
            #
          </th>
          {columns.map((c) => (
            <th
              key={c.key}
              className="whitespace-nowrap border-b border-r px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground last:border-r-0"
            >
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr>
            <td
              colSpan={columns.length + 1}
              className="px-3 py-8 text-center text-sm text-muted-foreground"
            >
              No records.
            </td>
          </tr>
        )}
        {rows.map((row, i) => (
          <tr key={i} className="odd:bg-muted/20 hover:bg-accent/40">
            <td className="border-b border-r px-2 py-1.5 text-right text-xs tabular-nums text-muted-foreground">
              {i + 1}
            </td>
            {columns.map((c) => {
              const numeric =
                c.type && c.type !== "text" && c.type !== "date" && c.type !== "bool"
              return (
                <td
                  key={c.key}
                  className={cn(
                    "max-w-[280px] truncate border-b border-r px-3 py-1.5 last:border-r-0",
                    numeric && "text-right tabular-nums",
                  )}
                  title={formatCell(row[c.key], c.type)}
                >
                  {formatCell(row[c.key], c.type)}
                </td>
              )
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/* -------------------------------------------------------- global dashboard */

function GlobalCard({ ds }: { ds: Datasource }) {
  const { data, isLoading } = useQuery({
    queryKey: ["datasource", ds.key],
    // 10 cards poll at once — keep the global view light.
    queryFn: () => sf.get<{ data: Row[]; count: number }>(ds.endpoint),
    refetchInterval: POLL.slow,
  })
  const rows = data?.data ?? []
  const metrics = ds.metrics(rows)
  const bpm = 62 + (rows.length % 24)

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border bg-card">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Database size={14} className="text-muted-foreground" />
          {ds.label}
        </div>
        <span className="flex items-center gap-1.5 text-xs font-medium text-success">
          <i className="sf-pulse-soft size-2 rounded-full bg-success" />
          Online · {rows.length} rows
        </span>
      </div>
      <div className="space-y-3 p-3">
        <Heartbeat color={HEX.success} bpm={bpm} label="live" />
        <div className="grid grid-cols-3 gap-2">
          {metrics.map((m) => (
            <Gauge key={m.label} value={m.value} max={m.max} label={m.label} suffix={m.suffix} />
          ))}
        </div>
        <div className="max-h-56 overflow-auto rounded-md border">
          {isLoading ? <Loading label="Loading…" /> : <DataTable columns={ds.columns} rows={rows} />}
        </div>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------- page */

type Tab = "global" | "browse"

function DatasourcesPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>("global")
  const [active, setActive] = useState(DATASOURCES[0])
  const fileRef = useRef<HTMLInputElement>(null)
  const [io, setIo] = useState("")
  const [busy, setBusy] = useState(false)

  const exportSnapshot = async () => {
    setBusy(true)
    setIo("Exporting…")
    try {
      const blob = await sf.blob("/datasources/export")
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = "smart_forge_schema.csv"
      a.click()
      URL.revokeObjectURL(url)
      setIo("Exported smart_forge_schema.csv")
    } catch {
      setIo("Export failed")
    } finally {
      setBusy(false)
    }
  }

  const importSnapshot = async (file: File) => {
    if (busy) return
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setIo("Please choose a .csv file")
      return
    }
    if (file.size > 25 * 1024 * 1024) {
      setIo("File too large (max 25 MB)")
      return
    }
    if (
      !window.confirm(
        "Import replaces ALL operational data with this snapshot. Continue?",
      )
    ) {
      return
    }
    setBusy(true)
    setIo("Importing…")
    try {
      const fd = new FormData()
      fd.append("file", file)
      const body = await sf.upload<{ summary?: Record<string, number> }>(
        "/datasources/import",
        fd,
      )
      const n = Object.values(body.summary ?? {}).reduce((a, b) => a + b, 0)
      // Refresh just the datasource views; other pages refetch on navigation.
      qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === "datasource" })
      setIo(`Imported ${n.toLocaleString()} records`)
    } catch (e) {
      setIo(`Import failed: ${e instanceof Error ? e.message : "error"}`)
    } finally {
      setBusy(false)
    }
  }

  const browse = useQuery({
    queryKey: ["datasource", active.key],
    queryFn: () => sf.get<{ data: Row[]; count: number }>(active.endpoint),
    refetchInterval: POLL.medium,
    enabled: tab === "browse",
  })
  const rows = browse.data?.data ?? []

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Datasources"
        description="Read-only, live views over the production database."
        actions={
        <div className="flex flex-wrap items-center gap-2">
          {io && <span className="text-xs text-muted-foreground">{io}</span>}
          <input
            ref={fileRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) importSnapshot(f)
              e.target.value = ""
            }}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
          >
            <Upload size={14} /> Import
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={exportSnapshot}>
            <Download size={14} /> Export
          </Button>
          <div className="flex items-center gap-1 rounded-lg border bg-card p-1">
            <TabBtn active={tab === "global"} onClick={() => setTab("global")} label="Global">
              <LayoutGrid size={14} /> Global
            </TabBtn>
            <TabBtn active={tab === "browse"} onClick={() => setTab("browse")} label="Database Tables">
              <Table2 size={14} /> Database Tables
            </TabBtn>
          </div>
        </div>
        }
      />

      {tab === "global" ? (
        <div className="grid gap-4 xl:grid-cols-2">
          {DATASOURCES.map((ds) => (
            <GlobalCard key={ds.key} ds={ds} />
          ))}
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
          <nav className="flex flex-col gap-1">
            {DATASOURCES.map((d) => (
              <button
                key={d.key}
                type="button"
                onClick={() => setActive(d)}
                className={cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors",
                  active.key === d.key
                    ? "bg-primary/10 font-medium text-foreground"
                    : "text-muted-foreground hover:bg-accent",
                )}
              >
                <Database size={15} />
                {d.label}
              </button>
            ))}
          </nav>

          <div className="min-w-0 rounded-xl border bg-card">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <div>
                <h2 className="text-base font-semibold">{active.label}</h2>
                <p className="text-xs text-muted-foreground">
                  <code className="rounded bg-muted px-1">{active.endpoint}</code> ·{" "}
                  {rows.length} rows · read-only
                </p>
              </div>
            </div>
            {browse.isLoading ? (
              <Loading label={`Loading ${active.label}…`} />
            ) : (
              <div className="max-h-[60vh] overflow-auto">
                <DataTable columns={active.columns} rows={rows} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function TabBtn({
  active,
  onClick,
  label,
  children,
}: {
  active: boolean
  onClick: () => void
  label: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={cn(
        "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
        active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent",
      )}
    >
      {children}
    </button>
  )
}
