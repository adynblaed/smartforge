// Response contracts for the data-platform API surface (/platform, /warehouse,
// /lake under /api/v1). The FastAPI handlers return plain dicts, so the shapes
// are captured here, derived line-by-line from
// backend/app/api/routes/{platform,warehouse,lake}.py and
// backend/app/dataplatform/pipeline/freshness.py.

/** Freshness band computed from the committed watermark (dead-man's switch). */
export type FreshnessStatus = "fresh" | "warning" | "stale" | "never_loaded"

/** GET /platform/health */
export interface PlatformHealth {
  warehouse: "ok" | "unavailable"
  duckdb_catalog: "ok" | "missing"
  lake_root: string
  lake_published: boolean
  environment: string
}

/** One row of GET /platform/freshness `tables` (pipeline/freshness.py). */
export interface FreshnessRow {
  table: string
  destination: string
  cadence: string
  status: FreshnessStatus
  lag_minutes: number | null
  last_load_id: string | null
  last_published_at: string | null
  source_scn: number | null
}

/** GET /platform/freshness */
export interface FreshnessReport {
  overall: "fresh" | "warning" | "stale"
  tables: FreshnessRow[]
}

/**
 * One entry of GET /platform/replication/tables — a registry contract joined
 * with its committed watermark + freshness. The freshness overlay fields are
 * absent until the table has watermark history.
 */
export interface ReplicationTable {
  table: string
  destination: string
  enabled: boolean
  cadence: string
  strategy: string
  primary_key: string[]
  cursor_column: string | null
  delete_strategy: string
  classification: string
  owner: string
  status?: FreshnessStatus
  lag_minutes?: number | null
  last_load_id?: string | null
  last_published_at?: string | null
  source_scn?: number | null
}

export interface ReplicationTablesResponse {
  data: ReplicationTable[]
  count: number
}

/** control.replication_runs row (GET /platform/replication/runs `runs`). */
export interface ReplicationRun {
  run_id: string
  kind: string
  status: string
  started_at: string | null
  completed_at: string | null
  detail: string | null
}

/** control.replication_table_runs row (`table_runs` in the same response). */
export interface ReplicationTableRun {
  run_id: string
  load_id: string | null
  source_schema: string
  source_table: string
  strategy: string
  status: string
  source_scn: number | null
  cursor_lower: string | null
  cursor_upper: string | null
  rows_extracted: number | null
  rows_written_to_lake: number | null
  rows_loaded_to_postgres: number | null
  rows_rejected: number | null
  error: string | null
  started_at: string | null
  completed_at: string | null
}

/** GET /platform/replication/runs */
export interface ReplicationRunsResponse {
  runs: ReplicationRun[]
  table_runs: ReplicationTableRun[]
}

/** audit.reconciliation_results row (GET /platform/reconciliation `data`). */
export interface ReconciliationResult {
  run_id: string
  source_schema: string
  source_table: string
  check_name: string
  source_value: string | number | null
  target_value: string | number | null
  passed: boolean
  checked_at: string
}

export interface ReconciliationResponse {
  data: ReconciliationResult[]
  count: number
}

/** GET /warehouse/datasets entry — allowlisted marts/api relations. */
export interface WarehouseDataset {
  dataset: string
  schema: string
  name: string
  engine: "postgres"
  certified: boolean
  column_count: number
}

export interface WarehouseDatasetsResponse {
  data: WarehouseDataset[]
  count: number
}

/** GET /warehouse/kpis — curated KPI block; values are null until built. */
export interface WarehouseKpisResponse {
  kpis: Record<string, number | string | null>
  generated_at: string
}

/** GET /warehouse/datasets/{dataset} — paginated rows + provenance meta. */
export interface WarehouseRowsResponse<T> {
  data: T[]
  count: number
  meta: {
    dataset: string
    engine: "postgres"
    generated_at: string
    limit: number
    offset: number
    filters: Record<string, string>
    elapsed_ms: number
  }
}

/**
 * One row of api.api_work_orders (dbt models/api/api_work_orders.sql) — the
 * certified, genealogy-enriched work-order contract behind the explorer.
 */
export interface ApiWorkOrderRow {
  work_order_uid: string
  work_order_id: number
  wo_number: string | null
  parent_work_order_uid: string | null
  root_work_order_uid: string | null
  genealogy_depth: number | null
  genealogy_path: string | null
  child_count: number | null
  is_leaf: boolean | null
  title: string | null
  wo_type: string | null
  item_no: string | null
  qty_ordered: number | null
  qty_completed: number | null
  status: string | null
  priority: string | null
  current_operation: string | null
  sales_order_no: string | null
  sales_order_line: number | null
  machine_code: string | null
  scheduled_at: string | null
  due_at: string | null
  completed_at: string | null
  is_closed: boolean | null
  labor_hours: number | null
  cost_total: number | null
  load_id: string | null
  extracted_at: string | null
}

/**
 * One row of api.api_mrp_supply_plan (dbt models/api/api_mrp_supply_plan.sql):
 * item × plan-date grain with demand/supply rollups and the projected
 * running balance classified against safety stock.
 */
export interface MrpPlanRow {
  plan_row_key: string
  item_no: string
  item_description: string | null
  item_type: string | null
  uom: string | null
  plan_date: string
  demand_qty: number | null
  supply_qty: number | null
  supply_work_orders: number | null
  opening_qty: number | null
  projected_balance: number | null
  safety_stock: number | null
  mrp_lead_time_days: number | null
  plan_status: "shortage" | "below_safety" | "covered"
  exception_desc: string | null
  plan_horizon_end: string | null
}

/** GET /lake/datasets entry — DuckDB relations over the published Parquet lake. */
export interface LakeDataset {
  dataset: string
  schema: string
  name: string
  engine: "duckdb"
  type: string
}

export interface LakeDatasetsResponse {
  data: LakeDataset[]
  count: number
}

/** GET /lake/loads entry — one published load manifest (provenance ledger). */
export interface LakeLoad {
  table: string
  destination: string
  load_id: string
  scn: number | null
  row_count: number | null
  file_count: number | null
  strategy: string
  status: string
  published_at: string | null
}

export interface LakeLoadsResponse {
  data: LakeLoad[]
  count: number
}
