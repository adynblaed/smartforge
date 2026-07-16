# SmartForge API (all under `/api/v1`)

**SmartForge v1.0.0 LTS.** Governed data-platform endpoint contracts:
[`CLAUDE.md`](../CLAUDE.md) §6; architecture: [`specs/ARCHITECTURE.md`](../specs/ARCHITECTURE.md) §4.6.

Machine: `GET /machines`, `GET /machines/{id}`, `GET /machines/{id}/telemetry`,
`GET /machines/{id}/health`, `POST /machines/{id}/telemetry`, `POST /machines/{id}/ask`.

Alerts: `GET /alerts`, `POST /alerts/{id}/acknowledge`, `POST /alerts/{id}/resolve`.

Work orders: `GET /work-orders`, `POST /work-orders`, `POST /work-orders/from-alert/{id}`,
`POST /work-orders/{id}/approve`, `POST /work-orders/{id}/sync-fiix`.

Factory intelligence: `POST /inspection-results`, `GET /inspections`, `GET /defects`,
`GET /oee`, `GET /production-trends`, `GET /machine-configurations` (+`/approve`),
`GET /recommendations` (+`/{id}/decision`).

ERP/MES: `GET /integrations/status`, `GET /integrations/events`,
`POST /integrations/erp/sync`, `POST /integrations/mes/sync`.

Incidents: `GET/POST /incidents`, `GET/POST /incidents/{id}/rca`.

Planning: `GET /planning/capacity`, `POST /planning/simulate`.

Supply chain: `GET /inventory`, `GET /suppliers`, `GET /supply-chain/risks`,
`GET /purchase-orders`, `GET /quotes`, `POST /quotes/generate`,
`GET /jobs`, `POST /jobs`, `POST /jobs/intake`, `POST /jobs/{id}/approve`.

AskAI: `POST /ask-ai/ask`, `POST /ask-ai/forge`, `GET/POST /ask-ai/documents`,
`GET /ask-ai/sessions`, `GET/POST/PATCH/DELETE /ask-ai/knowledge-bases[/{id}]`.

Customer (customer-scoped): `GET /customer/orders`, `GET /customer/orders/{id}`,
`POST /customer/ask`, `POST /customer/escalate`, `GET /customer/escalations`,
`POST /customer/escalations/{id}/respond`.

Metrics/exec: `GET /factory/kpis`, `GET /command-center`, `GET /metrics` (Prometheus).

Realtime: `WS /ws/telemetry`, `WS /ws/orders`.

Data platform (internal users; mutating ops superuser-only):
`GET /platform/health`, `GET /platform/freshness`,
`GET /platform/replication/tables`, `GET /platform/replication/runs`,
`GET /platform/reconciliation`, `POST /platform/discovery/run`,
`GET /platform/seed/plan`, `POST /platform/seed/confirm` (plan fingerprint +
confirmation phrase), `POST /platform/sync/run`.

Warehouse (certified marts/api schemas, read-only role, 15 s statement
timeout, `limit ≤ 1000`, allowlisted filters/order_by):
`GET /warehouse/datasets`, `GET /warehouse/datasets/{dataset}`,
`GET /warehouse/kpis`.

Lake (exploratory DuckDB views over published Parquet, read-only
connection, bound parameters): `GET /lake/datasets`,
`GET /lake/datasets/{dataset}`, `GET /lake/loads` (manifest provenance).

## Contract policy

- Everything is versioned under `/api/v1`; breaking changes ship under a
  new version prefix with a deprecation window and migration notes in
  `release-notes.md` (API-016).
- Responses from `/warehouse` and `/lake` carry `meta` provenance (engine,
  generated_at; freshness via `/platform/freshness` or the
  `api_replication_freshness` dataset).
- GET endpoints are safe/idempotent; there is no server-side result cache —
  any client/proxy cache key must include the bearer identity, dataset,
  filters, and pagination (API-013).
- Every response carries `X-Request-ID` for cross-layer correlation
  (API-014).

## Result formats & long-running queries (by design)

- **JSON is the only result format** on the governed analytical endpoints
  (API-021). Alternative formats (CSV/Arrow/Parquet) are deliberately not
  offered there so authorization, pagination, and schema contracts cannot
  be bypassed by an export path (API-010). The only tabular export is the
  app-data Datasources CSV (`/datasources/export`), which is
  authenticated, audited, and scoped to the operational DB.
- **No synchronous long-query lane** (API-020): every read is bounded
  (statement timeout, pagination cap, memory limits). Legitimately long
  analytics belong in the pipeline: they are materialized as dbt marts on
  schedule and then served as bounded reads. The only asynchronous
  operations are the superuser-gated `POST /platform/sync/run` and seed
  execution, which run as background tasks with status observable via
  `GET /platform/replication/runs`.
- **Provenance instead of export metadata** (API-022): since results are
  JSON reads, provenance ships inline — the `meta` block (dataset, engine,
  timing, generated_at) plus `/platform/freshness` and the
  `api_replication_freshness` dataset for load IDs, SCNs, and watermarks.
