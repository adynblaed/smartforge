# SmartForge Data Model

**SmartForge v1.0.0 LTS.**

All tables from the retired product spec (§5, consolidated into the
formal record under `specs/`) are implemented as SQLModel classes under
`app/models/` (one module per domain, re-exported from `app/models/__init__.py`).

Core: `users` (+`role`,`customer_id`), `factories`, `lines`, `machine`.
Telemetry: `telemetry_events`, `machine_health_scores`.
Maintenance: `alerts`, `work_orders`, `incidents`, `rca_records`.
Production: `jobs`, `production_runs`, `oee_metrics`.
Quality: `inspections`, `defects`.
Optimization: `machine_configurations`, `recommendations`.
Integration: `erp_sync_events`, `mes_sync_events`.
Supply chain: `suppliers`, `inventory_items`, `purchase_orders`, `quotes`.
Customer: `customer`, `customer_orders`, `customer_messages`, `escalations`.
Knowledge/AI: `knowledge_documents`, `askai_sessions`.
Audit: `audit_logs`.

Every operational table carries `factory_id` and/or `line_id` for multi-site
scaling. Migration: `app/alembic/versions/a1b2c3d4e5f6_smartforge_core_schema.py`.

## Analytics warehouse (`warehouse` database)

Separate logical database, schema-per-responsibility (PG-001), bootstrapped
idempotently by `python -m app.dataplatform.cli bootstrap`:

| Schema | Contents | Writer |
|---|---|---|
| `control` | `replication_watermarks`, `replication_runs`, `replication_table_runs`, `replication_manifests`, `schema_versions`, `seed_plans` | loader |
| `raw_oracle` | Faithful omega replicas + `_source_*`/`_load_id`/`_extracted_at`/`_is_deleted` metadata columns | loader (dlt merge) |
| `staging` / `intermediate` | dbt: deterministic rename/cast/dedupe; delete filtering | transformer |
| `marts` | `dim_machines/customers/suppliers/status`, `fct_production_runs/work_orders/quality_inspections/purchase_orders/telemetry_events` (+ `snap_suppliers` SCD2) | transformer |
| `api` | Certified products: `api_machine_health`, `api_production_summary`, `api_quality_summary`, `api_supply_chain_status`, `api_replication_freshness` | transformer |
| `audit` | `reconciliation_results`, `rejected_records` | loader |

The lake mirrors `raw_oracle` as immutable, manifested Parquet under
`LAKE_ROOT/published/...`, queryable through the read-only DuckDB catalog.
Source contracts (keys, cursors, cadence, delete strategy, classification,
owner) live in [`config/tables.yml`](../config/tables.yml).
