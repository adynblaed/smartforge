import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Plus, Search, X } from "lucide-react"
import { useState } from "react"

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
import { cn } from "@/lib/utils"
import { sf } from "@/smartforge/api"
import { HEX, KpiTile, PageHeader, Panel } from "@/smartforge/components"
import {
  buildDatasetQuery,
  clauseIsComplete,
  type FilterClause,
  fieldFor,
  genealogyLevelLabel,
  OPERATORS,
  WORK_ORDER_FIELDS,
} from "@/smartforge/explorer"
import {
  FreshnessBadge,
  formatLag,
  formatRunDuration,
  formatWhen,
  freshnessCounts,
  kpiLabel,
  RunStatusBadge,
  summarizeRuns,
} from "@/smartforge/platform"
import type {
  ApiWorkOrderRow,
  FreshnessReport,
  LakeDatasetsResponse,
  LakeLoadsResponse,
  PlatformHealth,
  ReconciliationResponse,
  ReplicationRunsResponse,
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

export const Route = createFileRoute("/_layout/data-platform")({
  component: DataPlatformPage,
  head: () => ({ meta: [{ title: "Data Platform - SmartForge" }] }),
})

/* -------------------------------------------------- work orders explorer */

const DEFAULT_EXPLORER_QUERY = buildDatasetQuery(
  [{ field: "is_closed", op: "eq", value: "false" }],
  { orderBy: "due_at", orderDir: "asc", limit: 100 },
)

// Read-only EDA over the certified api.api_work_orders contract: the query
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

  const query = useQuery({
    queryKey: ["data-platform", "work-orders-explorer", submitted],
    queryFn: () =>
      sf.get<WarehouseRowsResponse<ApiWorkOrderRow>>(
        `/warehouse/datasets/api.api_work_orders?${submitted}`,
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

        {/* results */}
        <Section query={query}>
          {(res) => (
            <>
              <MiniTable
                rows={res.data}
                rowKey={(row) => row.work_order_uid}
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
                    render: (row) => (
                      <div title={row.genealogy_path ?? undefined}>
                        <Badge variant="outline" className="text-xs">
                          {genealogyLevelLabel(row.genealogy_depth)}
                        </Badge>
                        {(row.child_count ?? 0) > 0 && (
                          <span className="ml-1 text-xs text-muted-foreground">
                            {row.child_count} child
                            {(row.child_count ?? 0) > 1 ? "ren" : ""}
                          </span>
                        )}
                      </div>
                    ),
                  },
                  { key: "item", label: "Item", render: (row) => row.item_no },
                  {
                    key: "qty",
                    label: "Qty",
                    align: "right",
                    render: (row) =>
                      `${row.qty_completed ?? 0}/${row.qty_ordered ?? 0}`,
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
                {res.data.length.toLocaleString()} · {res.meta.elapsed_ms}ms ·
                as of {formatWhen(res.meta.generated_at)} · certified contract
                api.api_work_orders
              </p>
            </>
          )}
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
  const runs = usePlatform<ReplicationRunsResponse>(
    "replication-runs",
    "/platform/replication/runs",
  )
  const reconciliation = usePlatform<ReconciliationResponse>(
    "reconciliation",
    "/platform/reconciliation",
    REFRESH_SLOW,
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

  const counts = freshness.data
    ? freshnessCounts(freshness.data.tables)
    : undefined
  const platformUp = health.data?.warehouse === "ok"
  const platformStatus = health.data
    ? platformUp
      ? "Operational"
      : "Degraded"
    : health.isError
      ? "Unreachable"
      : "…"

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Data Platform"
        description="Replication, freshness, reconciliation and the warehouse + lake serving layers — the platform's observability surface."
        actions={
          health.data && (
            <Badge variant="outline" className="capitalize">
              env: {health.data.environment}
            </Badge>
          )
        }
      />

      {/* (a) health summary tiles */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <KpiTile
          label="Platform"
          value={platformStatus}
          hint={
            health.data
              ? `warehouse ${health.data.warehouse} · duckdb ${health.data.duckdb_catalog} · lake ${health.data.lake_published ? "published" : "not published"}`
              : "probing stores…"
          }
          accent={platformUp ? HEX.success : HEX.danger}
        />
        <KpiTile
          label="Tables Tracked"
          value={counts ? (freshness.data?.tables.length ?? 0) : "—"}
          hint="enabled replication contracts"
        />
        <KpiTile
          label="Fresh"
          value={counts ? counts.fresh : "—"}
          hint="within cadence SLO"
          accent={HEX.success}
        />
        <KpiTile
          label="Warning"
          value={counts ? counts.warning : "—"}
          hint="lagging behind cadence"
          accent={HEX.warning}
        />
        <KpiTile
          label="Stale"
          value={counts ? counts.stale + counts.never_loaded : "—"}
          hint={
            counts
              ? `incl. ${counts.never_loaded} never loaded`
              : "past error threshold"
          }
          accent={HEX.danger}
        />
      </div>

      {/* (b) replication freshness */}
      <Panel
        title="Replication Freshness"
        action={
          freshness.data && <FreshnessBadge status={freshness.data.overall} />
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
                  render: (t) => <FreshnessBadge status={t.status} />,
                },
              ]}
            />
          )}
        </Section>
      </Panel>

      {/* (b2) imported work orders: live, synced, queryable (read-only) */}
      <WorkOrdersExplorer />

      <div className="grid gap-6 xl:grid-cols-2">
        {/* (c) recent replication runs */}
        <Panel title="Recent Replication Runs">
          <Section query={runs}>
            {(res) => (
              <MiniTable
                rows={summarizeRuns(res.runs, res.table_runs)}
                rowKey={(r) => r.run_id}
                empty="No replication runs recorded yet."
                cols={[
                  {
                    key: "run",
                    label: "Run",
                    render: (r) => (
                      <div title={r.run_id}>
                        <div className="font-mono text-xs">
                          {r.run_id.slice(0, 8)}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {r.kind}
                        </div>
                      </div>
                    ),
                  },
                  {
                    key: "started",
                    label: "Started",
                    render: (r) => formatWhen(r.started_at),
                  },
                  {
                    key: "duration",
                    label: "Duration",
                    align: "right",
                    render: (r) =>
                      formatRunDuration(r.started_at, r.completed_at),
                  },
                  {
                    key: "tables",
                    label: "Tables",
                    align: "right",
                    render: (r) => r.tables.toLocaleString(),
                  },
                  {
                    key: "rows",
                    label: "Rows",
                    align: "right",
                    render: (r) => r.rows.toLocaleString(),
                  },
                  {
                    key: "status",
                    label: "Status",
                    render: (r) => <RunStatusBadge status={r.status} />,
                  },
                ]}
              />
            )}
          </Section>
        </Panel>

        {/* (d) reconciliation evidence */}
        <Panel title="Reconciliation Results">
          <Section query={reconciliation}>
            {(res) => (
              <MiniTable
                rows={res.data}
                rowKey={(r, i) => `${r.run_id}-${r.check_name}-${i}`}
                empty="No reconciliation checks recorded yet."
                cols={[
                  {
                    key: "table",
                    label: "Table",
                    render: (r) => `${r.source_schema}.${r.source_table}`,
                  },
                  {
                    key: "check",
                    label: "Check",
                    render: (r) => r.check_name.replace(/_/g, " "),
                  },
                  {
                    key: "source",
                    label: "Source",
                    align: "right",
                    render: (r) => r.source_value ?? "—",
                  },
                  {
                    key: "target",
                    label: "Target",
                    align: "right",
                    render: (r) => r.target_value ?? "—",
                  },
                  {
                    key: "result",
                    label: "Result",
                    render: (r) => (
                      <RunStatusBadge status={r.passed ? "passed" : "failed"} />
                    ),
                  },
                  {
                    key: "checked",
                    label: "Checked",
                    render: (r) => formatWhen(r.checked_at),
                  },
                ]}
              />
            )}
          </Section>
        </Panel>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        {/* (e) warehouse marts + KPIs */}
        <Panel title="Warehouse Marts & KPIs">
          <div className="flex flex-col gap-4">
            <Section query={warehouseKpis}>
              {(res) => (
                <div className="grid gap-3 sm:grid-cols-2">
                  {Object.entries(res.kpis).map(([key, value]) => (
                    <KpiTile
                      key={key}
                      label={kpiLabel(key)}
                      value={
                        value === null
                          ? "—"
                          : typeof value === "number"
                            ? value.toLocaleString()
                            : value
                      }
                      hint={`as of ${formatWhen(res.generated_at)}`}
                    />
                  ))}
                </div>
              )}
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
                  empty="No DuckDB relations published yet."
                  cols={[
                    {
                      key: "dataset",
                      label: "Dataset",
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
                  empty="No load manifests published yet."
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
                      label: "Published",
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
