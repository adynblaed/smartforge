import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Loader2, Plus, RefreshCw, Search, X } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useFeatures } from "@/hooks/useFeatures"
import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import { HEX, KpiTile, PageHeader, Panel } from "@/smartforge/components"
import { DatasetSizeChart } from "@/smartforge/DatasetSizeChart"
import {
  buildDatasetQuery,
  clauseIsComplete,
  descendantStats,
  type FilterClause,
  fieldFor,
  formatDescendants,
  genealogyLevelLabel,
  OPERATORS,
  WORK_ORDER_FIELDS,
} from "@/smartforge/explorer"
import {
  FreshnessBadge,
  formatLag,
  formatWhen,
  freshnessCounts,
  RunStatusBadge,
} from "@/smartforge/platform"
import type {
  ApiWorkOrderRow,
  FreshnessReport,
  LakeDatasetsResponse,
  LakeLoadsResponse,
  PlatformHealth,
  ReplicationTable,
  ReplicationTablesResponse,
  WarehouseDatasetsResponse,
  WarehouseKpisResponse,
  WarehouseRowsResponse,
} from "@/smartforge/platformTypes"
import {
  MiniTable,
  REFRESH_FAST,
  REFRESH_SLOW,
  Section,
  usePlatform,
} from "@/smartforge/platformUi"
import {
  queueTableSync,
  SyncNowButton,
  useSyncStatuses,
} from "@/smartforge/SyncNowButton"
import {
  type ChartView,
  DEFAULT_CHART_VIEW,
  WorkOrderCharts,
} from "@/smartforge/WorkOrderCharts"
import { WorkOrderGraph3D } from "@/smartforge/WorkOrderGraph3D"

export const Route = createFileRoute("/_layout/eda")({
  component: DataPlatformPage,
  head: () => ({ meta: [{ title: "EDA - SmartForge" }] }),
})

/** Mart KPI display: NUMERICs cross the JSON boundary as strings — coerce,
 * then format per kind ("—" while loading/unprovisioned). */
function martKpi(
  data: WarehouseKpisResponse | undefined,
  key: string,
  kind: "count" | "pct" | "usd" = "count",
): string {
  const raw = data?.kpis?.[key]
  if (raw == null) return "—"
  const n = Number(raw)
  if (!Number.isFinite(n)) return "—"
  if (kind === "pct") return `${n.toLocaleString()}%`
  if (kind === "usd")
    return `$${n.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`
  return n.toLocaleString()
}

/* -------------------------------------------------- work orders explorer */

const DEFAULT_EXPLORER_QUERY = buildDatasetQuery(
  [{ field: "is_closed", op: "eq", value: "false" }],
  { orderBy: "due_at", orderDir: "asc", limit: 100 },
)

// Read-only EDA over the certified work_orders contract (v1): the query
// builder emits the documented `column__op=value` grammar; the server
// re-validates every column/operator/value against its allowlist (IQ-004).
function WorkOrdersExplorer() {
  const [clauses, setClauses] = useState<FilterClause[]>([
    { field: "is_closed", op: "eq", value: "false" },
  ])
  const [orderBy, setOrderBy] = useState("due_at")
  const [orderDir, setOrderDir] = useState<"asc" | "desc">("asc")
  const [limit, setLimit] = useState(100)
  const [submitted, setSubmitted] = useState(DEFAULT_EXPLORER_QUERY)
  // Graph-node ⇄ table-row correlation (3D constellation selection).
  const [selectedUid, setSelectedUid] = useState<string | null>(null)
  // Chart view lives HERE (not in the Charts tab) so toggling Table ⇄
  // Charts restores the last chart exactly, against the active query.
  const [chartView, setChartView] = useState<ChartView>(DEFAULT_CHART_VIEW)
  const { enabled: featureEnabled } = useFeatures()
  const galaxyEnabled = featureEnabled("eda_galaxy")

  const query = useQuery({
    queryKey: ["eda", "work-orders-explorer", submitted],
    queryFn: () =>
      sf.get<WarehouseRowsResponse<ApiWorkOrderRow>>(
        `/warehouse/datasets/work_orders?${submitted}`,
      ),
    placeholderData: (previous) => previous,
    retry: false,
  })

  const update = (index: number, patch: Partial<FilterClause>) =>
    setClauses((current) =>
      current.map((clause, i) => {
        if (i !== index) return clause
        const next = { ...clause, ...patch }
        if (patch.field && patch.field !== clause.field) {
          // Field changed: reset to that type's first operator + empty value.
          const type = fieldFor(WORK_ORDER_FIELDS, patch.field)?.type ?? "text"
          next.op = OPERATORS[type][0].value
          next.value = ""
        }
        return next
      }),
    )

  const run = () =>
    setSubmitted(buildDatasetQuery(clauses, { orderBy, orderDir, limit }))

  return (
    <Panel
      title="Work Orders Explorer"
      action={
        <Badge variant="outline" className="text-xs">
          certified · read-only
        </Badge>
      }
    >
      <div className="flex flex-col gap-3">
        {/* 3D genealogy constellation — every queried order as a node,
            parent→child links as edges; updates with each Run query and
            correlates with the table selection below. Beta-flagged
            (eda_galaxy): beta clients, developers and superusers. */}
        {galaxyEnabled && query.data && (
          <WorkOrderGraph3D
            rows={query.data.data}
            selectedUid={selectedUid}
            onSelect={setSelectedUid}
          />
        )}

        {/* query builder */}
        <div className="flex flex-col gap-2">
          {clauses.map((clause, index) => {
            const field = fieldFor(WORK_ORDER_FIELDS, clause.field)
            const type = field?.type ?? "text"
            return (
              <div
                key={`clause-${index.toString()}`}
                className="flex flex-wrap items-center gap-2"
              >
                <span className="w-10 text-right text-xs text-muted-foreground">
                  {index === 0 ? "where" : "and"}
                </span>
                <Select
                  value={clause.field}
                  onValueChange={(value) => update(index, { field: value })}
                >
                  <SelectTrigger size="sm" className="w-44">
                    <SelectValue placeholder="Field" />
                  </SelectTrigger>
                  <SelectContent>
                    {WORK_ORDER_FIELDS.map((f) => (
                      <SelectItem key={f.key} value={f.key}>
                        {f.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select
                  value={clause.op}
                  onValueChange={(value) => update(index, { op: value })}
                >
                  <SelectTrigger size="sm" className="w-32">
                    <SelectValue placeholder="Operator" />
                  </SelectTrigger>
                  <SelectContent>
                    {OPERATORS[type].map((op) => (
                      <SelectItem key={op.value} value={op.value}>
                        {op.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {field?.options ? (
                  <Select
                    value={clause.value}
                    onValueChange={(value) => update(index, { value })}
                  >
                    <SelectTrigger size="sm" className="w-40">
                      <SelectValue placeholder="Value" />
                    </SelectTrigger>
                    <SelectContent>
                      {field.options.map((option) => (
                        <SelectItem key={option} value={option}>
                          {field.key === "genealogy_depth"
                            ? `${option} · ${genealogyLevelLabel(Number(option))}`
                            : option}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    className="h-8 w-48"
                    type={
                      type === "number"
                        ? "number"
                        : type === "date"
                          ? "date"
                          : "text"
                    }
                    placeholder="Value"
                    value={clause.value}
                    onChange={(event) =>
                      update(index, { value: event.target.value })
                    }
                    onKeyDown={(event) => event.key === "Enter" && run()}
                  />
                )}
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7"
                  aria-label="Remove filter"
                  onClick={() =>
                    setClauses((current) =>
                      current.filter((_, i) => i !== index),
                    )
                  }
                >
                  <X className="size-3.5" />
                </Button>
              </div>
            )
          })}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setClauses((current) => [
                  ...current,
                  { field: "item_no", op: "eq", value: "" },
                ])
              }
            >
              <Plus className="size-3.5" /> Add filter
            </Button>
            <span className="ml-2 text-xs text-muted-foreground">order by</span>
            <Select value={orderBy} onValueChange={setOrderBy}>
              <SelectTrigger size="sm" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {WORK_ORDER_FIELDS.map((f) => (
                  <SelectItem key={f.key} value={f.key}>
                    {f.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={orderDir}
              onValueChange={(value) => setOrderDir(value as "asc" | "desc")}
            >
              <SelectTrigger size="sm" className="w-24">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="asc">asc</SelectItem>
                <SelectItem value="desc">desc</SelectItem>
              </SelectContent>
            </Select>
            <span className="text-xs text-muted-foreground">limit</span>
            <Select
              value={String(limit)}
              onValueChange={(value) => setLimit(Number(value))}
            >
              <SelectTrigger size="sm" className="w-24">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[100, 250, 500, 1000].map((n) => (
                  <SelectItem key={n} value={String(n)}>
                    {n}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button size="sm" onClick={run}>
              <Search className="size-3.5" /> Run query
            </Button>
            {clauses.some((c) => !clauseIsComplete(c)) && (
              <span className="text-xs text-muted-foreground">
                incomplete filters are skipped
              </span>
            )}
          </div>
        </div>

        {/* results — the same filtered rows, as a table or as charts */}
        <Section query={query}>
          {(res) => {
            // Downstream associations across the loaded set (O(n), ≤ the
            // server cap) — powers the Genealogy column stats.
            const genealogy = descendantStats(res.data)
            return (
              <Tabs defaultValue="table">
                <TabsList>
                  <TabsTrigger value="table">Table</TabsTrigger>
                  <TabsTrigger value="charts">Charts</TabsTrigger>
                </TabsList>
                <TabsContent value="charts">
                  <WorkOrderCharts
                    rows={res.data}
                    view={chartView}
                    onViewChange={setChartView}
                  />
                </TabsContent>
                <TabsContent value="table" className="flex flex-col gap-3">
                  <MiniTable
                    rows={res.data}
                    rowKey={(row) => row.work_order_uid}
                    selectedKey={selectedUid}
                    onRowClick={(row) =>
                      setSelectedUid(
                        row.work_order_uid === selectedUid
                          ? null
                          : row.work_order_uid,
                      )
                    }
                    empty="No work orders match this query — seed the platform or relax the filters."
                    cols={[
                      {
                        key: "wo",
                        label: "Work Order",
                        render: (row) => (
                          <div>
                            <div className="font-medium">{row.wo_number}</div>
                            <div
                              className="max-w-[220px] truncate text-xs text-muted-foreground"
                              title={row.title ?? undefined}
                            >
                              {row.title}
                            </div>
                          </div>
                        ),
                      },
                      {
                        key: "genealogy",
                        label: "Genealogy",
                        render: (row) => {
                          const downstream = formatDescendants(
                            genealogy.get(row.work_order_uid),
                          )
                          return (
                            <div title={row.genealogy_path ?? undefined}>
                              <Badge variant="outline" className="text-xs">
                                {genealogyLevelLabel(row.genealogy_depth)}
                              </Badge>
                              {downstream ? (
                                <span className="ml-1 text-xs text-muted-foreground">
                                  {downstream}
                                </span>
                              ) : (
                                (row.child_count ?? 0) > 0 && (
                                  <span className="ml-1 text-xs text-muted-foreground">
                                    {row.child_count} child
                                    {(row.child_count ?? 0) > 1 ? "ren" : ""}{" "}
                                    (filtered out)
                                  </span>
                                )
                              )}
                            </div>
                          )
                        },
                      },
                      {
                        key: "item",
                        label: "Item",
                        render: (row) => row.item_no,
                      },
                      {
                        key: "qty",
                        label: "Qty",
                        align: "right",
                        // NUMERICs arrive as strings — normalize for display.
                        render: (row) =>
                          `${Number(row.qty_completed ?? 0)}/${Number(row.qty_ordered ?? 0)}`,
                      },
                      {
                        key: "status",
                        label: "Status",
                        render: (row) => (
                          <span>
                            {row.status}
                            {row.current_operation && (
                              <span className="ml-1 text-xs text-muted-foreground">
                                @ {row.current_operation}
                              </span>
                            )}
                          </span>
                        ),
                      },
                      {
                        key: "machine",
                        label: "Machine",
                        render: (row) => row.machine_code ?? "—",
                      },
                      {
                        key: "so",
                        label: "Sales Order",
                        render: (row) =>
                          row.sales_order_no
                            ? `${row.sales_order_no} · L${row.sales_order_line ?? "?"}`
                            : "—",
                      },
                      {
                        key: "due",
                        label: "Due",
                        render: (row) => formatWhen(row.due_at),
                      },
                      {
                        key: "uid",
                        label: "UUID",
                        render: (row) => (
                          <span
                            className="font-mono text-xs text-muted-foreground"
                            title={row.work_order_uid}
                          >
                            {row.work_order_uid.slice(0, 8)}…
                          </span>
                        ),
                      },
                    ]}
                  />
                  <p className="text-xs text-muted-foreground">
                    {res.count.toLocaleString()} matching · showing{" "}
                    {res.data.length.toLocaleString()} · {res.meta.elapsed_ms}ms
                    · as of {formatWhen(res.meta.generated_at)} · certified
                    contract {res.meta.dataset}
                    {res.meta.version ? ` (${res.meta.version})` : ""}
                  </p>
                </TabsContent>
              </Tabs>
            )
          }}
        </Section>
      </div>
    </Panel>
  )
}

/* -------------------------------------------------------------------- page */

function DataPlatformPage() {
  const health = usePlatform<PlatformHealth>("health", "/platform/health")
  const freshness = usePlatform<FreshnessReport>(
    "freshness",
    "/platform/freshness",
  )
  const tables = usePlatform<ReplicationTablesResponse>(
    "replication-tables",
    "/platform/replication/tables",
  )
  const warehouseDatasets = usePlatform<WarehouseDatasetsResponse>(
    "warehouse-datasets",
    "/warehouse/datasets",
    REFRESH_SLOW,
  )
  const warehouseKpis = usePlatform<WarehouseKpisResponse>(
    "warehouse-kpis",
    "/warehouse/kpis",
    REFRESH_SLOW,
  )
  const lakeDatasets = usePlatform<LakeDatasetsResponse>(
    "lake-datasets",
    "/lake/datasets",
    REFRESH_SLOW,
  )
  const lakeLoads = usePlatform<LakeLoadsResponse>(
    "lake-loads",
    "/lake/loads",
    REFRESH_SLOW,
  )

  // Per-table sync feedback: a triggered row shows a spinner in place of
  // its freshness badge until its watermark advances (freshness polls
  // every 30s). Sync All enqueues every enabled contract sequentially —
  // the server's single worker drains them, so no trigger can conflict.
  const { enabled: pageFeature } = useFeatures()
  const canSync = pageFeature("platform_ops")
  const [rowSyncing, setRowSyncing] = useState<Record<string, string | null>>(
    {},
  )
  const markRowSyncing = (table: string, watermark: string | null) =>
    setRowSyncing((current) => ({ ...current, [table]: watermark }))
  const tablesData = tables.data
  useEffect(() => {
    if (!tablesData) return
    setRowSyncing((current) => {
      let changed = false
      const next = { ...current }
      for (const t of tablesData.data) {
        if (
          t.table in next &&
          next[t.table] !== (t.last_published_at ?? null)
        ) {
          delete next[t.table]
          changed = true
        }
      }
      return changed ? next : current
    })
  }, [tablesData])
  // Server-side each sync gets three self-healing attempts; poll the live
  // status so a row whose sync exhausted its retries drops its spinner and
  // reports the failure (the Sync button stays for another try).
  const anyRowSyncing = Object.keys(rowSyncing).length > 0
  const { byTable: syncStatuses } = useSyncStatuses(anyRowSyncing)
  useEffect(() => {
    if (!anyRowSyncing) return
    setRowSyncing((current) => {
      let changed = false
      const next = { ...current }
      for (const table of Object.keys(current)) {
        if (syncStatuses.get(table.toUpperCase())?.status === "failed") {
          delete next[table]
          changed = true
          toast.error(`Sync failed for ${table} — you can retry.`)
        }
      }
      return changed ? next : current
    })
  }, [anyRowSyncing, syncStatuses])
  const syncAll = async () => {
    const list = tablesData?.data.filter((t) => t.enabled) ?? []
    for (const t of list) {
      try {
        await queueTableSync(t.table)
        markRowSyncing(t.table, t.last_published_at ?? null)
      } catch {
        toast.error(`Failed to queue ${t.table}`)
      }
    }
    toast.success(`Queued ${list.length} tables for sync`)
  }

  const counts = freshness.data
    ? freshnessCounts(freshness.data.tables)
    : undefined
  const platformUp = health.data?.warehouse === "ok"
  const platformStatus = health.data
    ? platformUp
      ? "Synced"
      : "Degraded"
    : health.isError
      ? "Unreachable"
      : "…"

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Exploratory Data Analysis"
        description="Replication, freshness, reconciliation and the warehouse + lake serving layers — the platform's observability surface."
        actions={
          health.data && (
            <Badge variant="outline" className="capitalize">
              env: {health.data.environment}
            </Badge>
          )
        }
      />

      {/* (a0) mart dashboards — headline business KPIs from the certified
          warehouse marts (v1/kpis). NUMERICs arrive as strings; coerce. */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <KpiTile
          label="Open Work Orders"
          value={martKpi(warehouseKpis.data, "open_work_orders")}
          hint="not yet closed"
          accent={HEX.info}
        />
        <KpiTile
          label="Quality Pass Rate"
          value={martKpi(warehouseKpis.data, "quality_pass_rate_30d", "pct")}
          hint="inspections passed, last 30 days"
          accent={HEX.success}
        />
        <KpiTile
          label="Open Backlog Value"
          value={martKpi(warehouseKpis.data, "open_backlog_value", "usd")}
          hint="open sales-order lines"
        />
        <KpiTile
          label="Machines Tracked"
          value={martKpi(warehouseKpis.data, "machines_tracked")}
          hint="replicated machine dimension"
        />
        <KpiTile
          label="Closed Work Orders (30d)"
          value={martKpi(warehouseKpis.data, "closed_work_orders_30d")}
          hint="completed in the last 30 days"
          accent={HEX.success}
        />
      </div>

      {/* (a) health summary tiles */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <KpiTile
          label="Omega"
          value={platformStatus}
          hint={
            health.data
              ? `data warehouse ${health.data.warehouse} · data lake ${health.data.duckdb_catalog === "ok" && health.data.lake_published ? "ok" : "not ready"}`
              : "probing stores…"
          }
          accent={platformUp ? HEX.success : HEX.danger}
        />
        <KpiTile
          label="Tables Tracked"
          value={counts ? (freshness.data?.tables.length ?? 0) : "—"}
          hint="data contracts ok"
        />
        <KpiTile
          label="Fresh"
          value={counts ? counts.fresh : "—"}
          hint="recent updates"
          accent={HEX.success}
        />
        <KpiTile
          label="Warning"
          value={counts ? counts.warning : "—"}
          hint="updates lagging"
          accent={HEX.warning}
        />
        <KpiTile
          label="Stale"
          value={counts ? counts.stale + counts.never_loaded : "—"}
          hint={counts ? "updates behind" : "past error threshold"}
          accent={HEX.danger}
        />
      </div>

      {/* (b) imported work orders: live, synced, queryable (read-only) */}
      <WorkOrdersExplorer />

      {/* (b2) replication freshness */}
      <Panel
        title="Recent Updates"
        action={
          <div className="flex items-center gap-2">
            {canSync && (
              <Button
                size="sm"
                variant="outline"
                className="h-7 gap-1.5 text-xs"
                onClick={syncAll}
              >
                <RefreshCw className="size-3.5" /> Sync All
              </Button>
            )}
            {freshness.data && (
              <FreshnessBadge status={freshness.data.overall} />
            )}
          </div>
        }
      >
        <Section query={tables}>
          {(res) => (
            <MiniTable
              rows={res.data}
              rowKey={(t) => t.table}
              empty="No replication contracts registered."
              cols={[
                {
                  key: "table",
                  label: "Table",
                  render: (t) => (
                    <div className={cn(!t.enabled && "opacity-50")}>
                      <div className="font-medium">{t.table}</div>
                      <div className="text-xs text-muted-foreground">
                        → {t.destination}
                        {!t.enabled && " · disabled"}
                      </div>
                    </div>
                  ),
                },
                { key: "cadence", label: "Cadence", render: (t) => t.cadence },
                {
                  key: "strategy",
                  label: "Strategy",
                  render: (t) => t.strategy.replace(/_/g, " "),
                },
                {
                  key: "watermark",
                  label: "Watermark",
                  render: (t) => formatWhen(t.last_published_at),
                },
                {
                  key: "lag",
                  label: "Lag",
                  align: "right",
                  render: (t) => formatLag(t.lag_minutes),
                },
                {
                  key: "status",
                  label: "Status",
                  render: (t) =>
                    rowSyncing[t.table] !== undefined ? (
                      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <Loader2 className="size-3.5 animate-spin" /> syncing…
                      </span>
                    ) : (
                      <FreshnessBadge status={t.status} />
                    ),
                },
                ...(canSync
                  ? [
                      {
                        key: "sync",
                        label: "Sync",
                        render: (t: ReplicationTable) => (
                          <SyncNowButton
                            table={t.table}
                            onStarted={() =>
                              markRowSyncing(
                                t.table,
                                t.last_published_at ?? null,
                              )
                            }
                          />
                        ),
                      },
                    ]
                  : []),
              ]}
            />
          )}
        </Section>
      </Panel>

      <div className="grid gap-6 xl:grid-cols-2">
        {/* (e) warehouse marts — dataset catalogue + a high-level size
            comparison; the headline KPI tiles already live at the top */}
        <Panel title="Warehouse Marts & Datasets">
          <div className="flex flex-col gap-4">
            <Section query={warehouseDatasets}>
              {(res) => <DatasetSizeChart datasets={res.data} />}
            </Section>
            <Section query={warehouseDatasets}>
              {(res) => (
                <MiniTable
                  rows={res.data}
                  rowKey={(d) => d.dataset}
                  empty="No marts built yet — run the dbt build."
                  cols={[
                    {
                      key: "dataset",
                      label: "Dataset",
                      render: (d) => (
                        <span className="font-medium">{d.dataset}</span>
                      ),
                    },
                    { key: "schema", label: "Schema", render: (d) => d.schema },
                    {
                      key: "columns",
                      label: "Columns",
                      align: "right",
                      render: (d) => d.column_count.toLocaleString(),
                    },
                    {
                      key: "certified",
                      label: "Certified",
                      render: (d) => (
                        <RunStatusBadge
                          status={d.certified ? "passed" : "uncertified"}
                        />
                      ),
                    },
                  ]}
                />
              )}
            </Section>
          </div>
        </Panel>

        {/* (f) lake datasets + load manifests */}
        <Panel title="Lake Datasets & Load Manifests">
          <div className="flex flex-col gap-4">
            <Section query={lakeDatasets}>
              {(res) => (
                <MiniTable
                  rows={res.data}
                  rowKey={(d) => d.dataset}
                  empty="No DuckDB relations synced yet."
                  cols={[
                    {
                      key: "dataset",
                      label: "Dataset",
                      // Canonical ids straight from the API (omega.*).
                      render: (d) => (
                        <span className="font-medium">{d.dataset}</span>
                      ),
                    },
                    { key: "type", label: "Type", render: (d) => d.type },
                    { key: "engine", label: "Engine", render: (d) => d.engine },
                  ]}
                />
              )}
            </Section>
            <Section query={lakeLoads}>
              {(res) => (
                <MiniTable
                  rows={res.data}
                  rowKey={(l, i) => `${l.table}-${l.load_id}-${i}`}
                  empty="No load manifests synced yet."
                  cols={[
                    {
                      key: "table",
                      label: "Table",
                      render: (l) => (
                        <div>
                          <div className="font-medium">{l.table}</div>
                          <div
                            className="font-mono text-xs text-muted-foreground"
                            title={l.load_id}
                          >
                            {l.load_id.slice(0, 12)}
                          </div>
                        </div>
                      ),
                    },
                    {
                      key: "rows",
                      label: "Rows",
                      align: "right",
                      render: (l) => l.row_count?.toLocaleString() ?? "—",
                    },
                    {
                      key: "files",
                      label: "Files",
                      align: "right",
                      render: (l) => l.file_count?.toLocaleString() ?? "—",
                    },
                    {
                      key: "strategy",
                      label: "Strategy",
                      render: (l) => l.strategy.replace(/_/g, " "),
                    },
                    {
                      key: "status",
                      label: "Status",
                      render: (l) => <RunStatusBadge status={l.status} />,
                    },
                    {
                      key: "published",
                      label: "Synced",
                      render: (l) => formatWhen(l.published_at),
                    },
                  ]}
                />
              )}
            </Section>
          </div>
        </Panel>
      </div>

      <p className="text-xs text-muted-foreground">
        Freshness derives from committed watermarks (dead-man's-switch — a dead
        scheduler surfaces as stale data, never false health). Polling every{" "}
        {REFRESH_FAST / 1000}s; catalogs every {REFRESH_SLOW / 1000}s.
      </p>
    </div>
  )
}
