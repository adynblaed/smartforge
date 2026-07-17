# SmartForge Analytics Data Platform — Architecture (v1.0.0 LTS)

**Status:** Ratified for v1.0.0 LTS (2026-07-16).
**This document is the specification of record.** It formalizes — and
supersedes — the retired drafting documents (the *Data Warehouse & Lake
Specs* PDF and the *Migration* blueprint, both consolidated here at
ratification); the marked formal acceptance record is
[`CHECKLIST.md`](CHECKLIST.md), and the release feature matrix is
[`FEATURES.md`](FEATURES.md).
**Companions:** [`CLAUDE.md`](../CLAUDE.md) (working guide),
[`docs/data-platform.md`](../docs/data-platform.md) (governance handbook),
[`QUICKSTART.md`](../QUICKSTART.md) (operator walkthrough), and the
[runbooks](#12-runbook-index).

> Historical citations of the form *"Migration §4"* / *"Specs §27"*
> (here, in `CHECKLIST.md`, and in the runbooks) refer to sections of
> those retired drafts and are preserved verbatim for traceability; their
> substance lives in this document.

> **One-line framing** (Migration §Exec): *an hourly ELT pipeline using
> query-based incremental extraction (high-watermark) from a read-only
> Oracle source, landing immutable Parquet, transformed via dual-target dbt
> into conformed and curated models, materialized in DuckDB (lake) and
> PostgreSQL (served warehouse), orchestrated by a single-flight worker,
> with periodic reconciliation to catch deletes — a **replication + ELT
> pipeline, not a migration**: it runs until the legacy source retires.*

---

## 1. System context

```
┌─────────────────────┐
│ omega Oracle        │  Source of truth. READ-ONLY identity, verified at
│ (READ-ONLY, legacy) │  every connect; we never write here (§3).
└─────────┬───────────┘
          │ (1) EXTRACT — oracledb thin, keyset pagination, AS OF SCN seeds,
          │     high-watermark increments, UUIDv5 identity stamping
          ▼
┌───────────────────────────────────────────────────────────┐
│ CANONICAL PARQUET LAKE (bronze / raw floor)                │
│ {LAKE_ROOT}/published/omega/<schema>/<table>/              │
│   snapshot_scn=… | increment_date=… / load_id=… /          │
│   part-*.parquet + manifest.json — IMMUTABLE, manifested   │
└─────────┬──────────────────────────────┬──────────────────┘
          │ (2a) DuckDB catalog          │ (2b) dlt merge (PK, idempotent)
          ▼                              ▼
┌────────────────────────┐   ┌─────────────────────────────────┐
│ DuckDB (LAKE engine)   │   │ PostgreSQL `warehouse` database │
│ read-only views over   │   │ raw_oracle → staging →          │
│ published Parquet      │   │ intermediate → marts / api      │
└─────────┬──────────────┘   └───────────┬─────────────────────┘
          │ (3) TRANSFORM — one dbt project, BOTH targets (silver → gold)
          ▼                              ▼
   exploratory EDA               certified data products
          │                              │
          └────────────┬─────────────────┘
                       ▼ (4) SERVE — FastAPI /api/v1
        /lake/* (exploratory)   /warehouse/* (certified)   /platform/* (ops)
                       ▼
        React frontend: Data Platform page (+ Work Orders explorer),
        MRP page, Datasources — read-only analytics surfaces
```

Orchestration: `platform-worker` (hourly dispatch, UTC, single-flight).
Observability: control/audit schemas, freshness dead-man's switch,
Prometheus pipeline metrics, Grafana dashboards (§7).

**Single extract, dual serve** (Migration §4): extraction lands once into
Parquet; *both* stores derive from that same publication. The stores can
never diverge at the raw layer, the fragile source is never double-hit,
and Parquet remains the neutral, portable interchange (anti-lock-in, D3).

## 2. Principles, vocabulary & layering

The blueprint's guiding principles (Migration §1) are load-bearing here:
**idempotency everywhere · raw is immutable · portability over convenience
· small observable restartable units · everything as code · fail loud,
degrade safe.** The shared vocabulary of Migration §2 (ELT, high-watermark,
medallion, SCD, reconciliation, data contract) is used unchanged.

Medallion mapping (Specs §5, Migration §2):

| Medallion | This platform | Materialization |
|---|---|---|
| Bronze (raw) | Published Parquet lake + `raw_oracle` schema (both stores) | Immutable files / dlt-merged tables |
| Silver (conformed) | dbt `staging` (rename/cast/dedupe only, DBT-006) + `intermediate` | Views |
| Gold (curated) | dbt `marts` (dims + facts) and `api` (certified data products) | Tables / views, contract-stable (API-016) |

## 3. The critical constraint: read-only source

Read-only access rules out log-based CDC, GoldenGate, triggers, and
materialized-view logs (Migration §3, decision D2). The platform therefore
uses **query-based high-watermark extraction** with these engineered
consequences:

1. **Hard deletes are invisible** → soft-delete columns captured naturally;
   weekly key reconciliation soft-marks vanished rows (`_is_deleted`);
   dbt staging filters them (INC-007).
2. **No cross-table transactional guarantee** → seeds extract every table
   `AS OF SCN` at one captured boundary (SEED-001 Method A); increments
   use fixed upper bounds + overlap + idempotent merge (INC-002/003/004).
3. **We are a tenant** → keyset pagination (never OFFSET), bounded fetch
   sizes, small connection pool, per-call timeout, off-peak seed windows
   agreed with the DBA (ORA-007, Gotchas §10.1).
4. **`updated_at` columns lie** → discovery verifies PK and cursor per
   table against the dictionary and the operator confirms every write path
   moves the cursor before seeding (SRC-003/004).

## 4. Component architecture

All paths below `backend/app/dataplatform/` unless noted.

### 4.1 Contracts & schema governance (fail-closed)

- `config/tables.yml` — one reviewed **replication contract** per table
  (key, cursor, cadence, strategy, delete policy, classification, owner,
  control totals, surrogate UUIDs). *No contract, no replication*
  (`registry.py`, DCT-001). 14 contracts at v1.0.0.
- `config/type_mappings.yml` — explicit Oracle→Postgres/Arrow/DuckDB type
  rules; an unmapped type **fails discovery closed** rather than being
  guessed (DCT-002/008) — NUMBER maps to exact decimals, never float
  (Gotchas: precision loss corrupts money).
- **Schema drift**: per-table schema hash recorded at every sync; a change
  pauses that table (and only that table) for a named human review
  (`state.record_schema_version`, DCT-007/010 →
  [`runbooks/schema_drift.md`](../runbooks/schema_drift.md)).

### 4.2 Extraction (`oracle/`)

`oracledb` thin driver (no Instant Client, D8), read-only **proven at every
connect** — session privileges and object grants enumerated; any write
capability is fatal (`connection.verify_read_only`, ORA-001..003). Explicit
Arrow schemas (never per-batch inference), keyset pagination over the PK,
`AS OF SCN` for seeds, cursor windows for increments, UTF-8 forced,
ingestion metadata stamped on every record
(`_source_system/_source_schema/_source_table/_source_scn/_load_id/
_extracted_at/_is_deleted`, DCT-012).

**Deterministic identity (DCT-011):** contracts may declare
`surrogate_uids`; the extractor stamps **UUIDv5** columns (fixed platform
namespace, `uids.py`) so entity identity is stable across reseeds and
replays and identical in both stores. Cross-table references reproduce the
referenced entity's UUID — the mechanism behind the work-order genealogy
(root → child → grandchild) resolved in dbt.

### 4.3 Lake (`lake/`)

Staging → validate → **atomic publish** (directory move; consumers never
observe a partial dataset) with a `manifest.json` per load: source SCN,
row/file counts, schema hash, files (SEED-005/007, LAKE-001/004).
Published Parquet is **immutable** — corrections are a new `load_id`;
snapshots prune to `LAKE_RETAINED_SNAPSHOTS`; abandoned staging directories
are quarantined by dispatcher maintenance (LAKE-011). The DuckDB catalog is
a **rebuildable artifact** of `CREATE OR REPLACE VIEW` over published
Parquet — one writer (`platform-worker`), all other opens `read_only=True`
(DDB-002); API queries run under an interrupt watchdog that maps overruns
to HTTP 504 (DDB-006).

### 4.4 Warehouse (`warehouse/`)

Separate `warehouse` PostgreSQL database, 7 schemas, **4 role-separated
identities** (§6). Loads apply published Parquet via **dlt merge** on the
contract PK (idempotent, INC-004) with a strict load-order guard — an
older SCN can never overwrite newer state (INC-006). Bootstrap DDL is
idempotent and injection-safe (identifiers allowlisted; secrets are
quote-doubled top-level literals never embedded in dollar-quoted blocks,
SEC-001).

### 4.5 Transform (dbt, dual-target)

One project (`dbt/`), two targets: `warehouse` (postgres) and `lake`
(duckdb) — identical models, dialect-neutral SQL with engine differences
isolated in macros (`latest_by_key`, `months_ago`, `time_series_index`;
DBT-010, D7). Staging dedupes raw by PK/SCN and filters soft-deletes;
`int_work_order_genealogy` resolves the parent/child/grandchild tree by
recursive CTE; marts are explicit-grain dims/facts; `api` models are the
**certified, contract-stable data products** (DBT-007/API-016), including
the `api_trailing_windows` 3/6/12-month EDA library. dbt tests (PK
uniqueness, relationships, accepted values, control-total and scrap-rate
singular tests) run in every build; failures block mart publication while
raw stays intact — marts go *visibly* stale, never silently wrong
(DBT-008). Source freshness thresholds mirror the cadence SLOs. Exposures
register every consumer for impact analysis (DBT-013). Time columns of
every fact are indexed on PostgreSQL via post-hook (a deliberate no-op on
DuckDB, whose zone maps prune scans).

### 4.6 Serving APIs (`backend/app/api/routes/{platform,warehouse,lake}.py`)

Contract rules enforced uniformly (API-002/003/006/007/008/009/012/014):
Pydantic-typed responses; identifiers only from server-side allowlists;
data values always bound parameters; mandatory pagination with hard caps;
`READ ONLY` transactions armed before statement timeouts (and re-armed
after rollbacks); errors never leak SQL/paths/stacks; provenance `meta`
(engine, generated_at, elapsed_ms) on every response; `X-Request-ID`
correlation. Filter grammar: `column[__op]=value`,
op ∈ eq/neq/gt/gte/lt/lte/contains, values typed against the catalog.
**API traffic never touches Oracle** (API-001); the superuser `/platform`
control-plane ops (discovery/seed/sync) are the deliberate, lock-guarded
exception (§4.8).

### 4.7 Frontend surfaces (`frontend/`)

Read-only analytics UIs over the governed APIs: **Data Platform** page
(health, freshness, runs, reconciliation, warehouse KPIs, lake manifests,
and the **Work Orders explorer** — a query builder emitting the documented
filter grammar against `api.api_work_orders`), the **MRP** page
(time-phased plan from `api.api_mrp_supply_plan` with client-side-only
what-if), and Datasources. Every section degrades independently to an
informative "not provisioned" state — never a crash (BI-005).

### 4.8 Orchestration & single-flight

`platform-worker` (compose/Helm) runs the hourly dispatcher: drift check →
windowed extract → publish → load → dbt (both targets) → reconcile →
watermark → lake maintenance. **Every writer entry point** — dispatcher
tick, operator CLI `seed`/`sync`/`reconcile-deletes`, superuser API
`seed/confirm`+`sync/run` (409 when busy), and the dev `sample-seed` —
executes under one Postgres advisory lock (`state.pipeline_lock`,
INC-013): one writer at a time, regardless of which process initiates.
Orchestrator graduation path (cron → worker → Dagster) is decision D9;
review triggers are recorded in CLAUDE §13.

### 4.9 Development sandbox seed

`cli sample-seed` (refused outside `PLATFORM_ENV=development`) drives the
*real* pipeline over a deterministic in-repo dataset — three-level
work-order genealogy, open-order backlog, internally consistent MRP
pegging — so every environment tier has a matching workflow: **dev**
sample-seed · **staging** scratch-store rehearsal · **prod** gated SOP
(QUICKSTART Parts 1–3).

## 5. Data lifecycles & invariants

**Seed:** discover (read-only inference, PK/cursor verification, SCN
boundary) → fingerprinted plan → human confirmation (`SEED OMEGA`) →
`AS OF SCN` extract → staging → row-count validation → atomic publish →
dlt merge → schema version recorded → reconciliation (counts, PK
uniqueness, control totals source/lake/warehouse) → **watermark last** →
catalog refresh. Both stores provably derive from the same publication
(SEED-009).

**Incremental:** drift check (fail-closed pause) → windowed extract (fixed
upper bound, overlap on the lower) → same publish/load/reconcile → watermark
last. A failed stage leaves the watermark untouched; the next tick replays
the window safely (INC-004/005).

**Non-negotiable invariants** (CLAUDE §7.3): immutable publications ·
watermark-commits-last · one writer at a time under the advisory lock ·
no contract → no replication, unmapped types fail closed · Oracle is
read-only, verified, never load-bearing for serving (replay uses the lake,
DR-005).

## 6. Identity & access model (IAM-001..004)

| Identity | Scope |
|---|---|
| `omega_analytics_reader` | Oracle: CREATE SESSION + SELECT (+FLASHBACK); writes proven absent at every connect |
| `warehouse_loader` | Postgres: writes `raw_oracle`/`control`/`audit` only |
| `warehouse_transformer` | Postgres: reads raw, owns `staging`/`intermediate`/`marts`/`api` |
| `warehouse_api_reader` | Postgres: SELECT on `marts`/`api`/control views; sessions READ ONLY + statement timeout |
| DuckDB writer | `platform-worker` only; every other open is `read_only=True` |
| App RBAC | superuser / internal / customer (FastAPI dependencies + role-aware rate limiting) |

Certified vs exploratory consumption is a hard split (IQ-010): certified
numbers come only from warehouse `marts`/`api`; the lake is exploratory.

## 7. Observability & performance

- **Freshness dead-man's switch** (OBS-003): per-table lag computed from
  *committed watermarks* — a dead scheduler surfaces as stale data, never
  as false health. `GET /platform/freshness` + the Data Platform page.
- **Lineage:** every load traceable run → load_id → SCN → manifest →
  warehouse rows (`control.*`); reconciliation evidence persisted in
  `audit.reconciliation_results`, including control totals on financial
  columns (DQ-002).
- **Pipeline KPIs** (OBS-008): Prometheus instruments
  (`smartforge_pipeline_*` — rows/bytes counters, per-stage duration
  histograms, last-run gauges, run outcomes, scheduler tick failures) from
  every process; a per-run migration KPI block (rows, bytes, duration,
  rows/s, Mbps, success rate) on run results and control records; one
  grep-able summary log line per run. Scraped from the worker (`:9108`)
  and `GET /api/v1/metrics`; Grafana ships the "Data Platform Pipeline"
  dashboard.
- **Query telemetry:** one value-free log line per governed read (dataset,
  rows, elapsed_ms, request ID — never data values, OBS-006).
- **Performance:** perf-regression lane in CI
  (`tests_dataplatform/test_perf_smoke.py`); time-series indexes on fct
  time columns; trailing-window library keeps common EDA bounded. SLOs and
  measured-baseline capture: `docs/data-platform.md` §8 (exception E3).

## 8. Failure handling, degradation & self-healing

Every long-running path has a ceiling; every failure degrades safely:

| Pressure point | Mechanism | Surface |
|---|---|---|
| Oracle call hangs | per-call timeout (`OMEGA_ORACLE_CALL_TIMEOUT_SECONDS`) | run fails, watermark untouched, next tick replays |
| Warehouse unreachable | `connect_timeout=5`, pool pre-ping | fast 503 with safe body + server-side warning |
| Long governed read (PG) | READ ONLY + statement timeout on every read (incl. discovery, KPIs — re-armed after rollback) | 503/422, never a hung handler |
| Long lake query (DuckDB) | interrupt watchdog at `API_STATEMENT_TIMEOUT_MS` | HTTP 504 |
| Concurrent writers | advisory single-flight lock on all writer entry points | 409 (API) / skip (dispatcher) / exit 1 (CLI) |
| dbt runaway | subprocess timeout (1h); failed tests block marts, raw retained | marts visibly stale |
| Bad/partial load | staged validation, quarantine, immutable prior loads, `table_prev` semantics | [`runbooks/rollback.md`](../runbooks/rollback.md) |
| Scheduler tick crash | swallow + count (`scheduler_tick_failures_total`) + next tick | Grafana + freshness dead-man |
| Poison rows / drift | fail-closed per-table pause; other tables keep flowing | [`runbooks/schema_drift.md`](../runbooks/schema_drift.md) |
| Frontend store outage | per-section queries, informative empty states, error boundaries | page never crashes |

## 9. Security & compliance

No secrets in code/config defaults/logs/errors (SEC-001; gitleaks +
pip-audit + osv-scanner in CI); known-default credentials refuse to start
outside development; TLS at Traefik and to the sources per environment
(E1 at Day-0); role-aware rate limiting (API-017); interactive API docs
(/docs, /redoc) served in every environment behind the `API_DOCS_ENABLED`
switch — the schema documents the contract only; every endpoint enforces
its own auth. GDPR & SOC 2 control mapping with data-subject procedures:
[`docs/compliance.md`](../docs/compliance.md). Access management, owners,
risk register, exceptions: [`docs/data-platform.md`](../docs/data-platform.md).

## 10. Environments & deployment

Compose is the production-shaped stack (Traefik TLS, Prometheus/Grafana
loopback-only); Kubernetes via Helm + Argo CD (`infra/`). Environment
separation is enforced, not conventional: dev-only tooling refuses other
tiers, per-tier secrets are validated at process start, and `.env.example`
is test-pinned to code defaults (config zero-drift guard). Day-0 go-live
procedure and pending action items: CLAUDE §13 (mirrors Specs §27).

## 11. Decision log (ratified)

D1 ELT (not ETL/"migration") · D2 high-watermark + reconcile (read-only
rules out log CDC) · D3 Parquet interchange · D4 DuckDB lake engine ·
D5 PostgreSQL warehouse · D6 dlt for load/merge · D7 dbt dual-target ·
D8 `oracledb` thin · D9 worker orchestration, Dagster graduation path ·
D10–D11 platform-specific rulings — full log with rationale and lock-in
notes in [`docs/data-platform.md`](../docs/data-platform.md) §Decisions and
Migration §16.

## 12. Runbook index

Operational procedures — each names its owner, preconditions, and
verification steps:

| Runbook | When to use |
|---|---|
| [`runbooks/initial_migration.md`](../runbooks/initial_migration.md) | The gated first-seed SOP (G0–G7): credentials → rehearsal → production seed → business validation |
| [`runbooks/operations.md`](../runbooks/operations.md) | Steady state: daily/weekly/monthly calendar, pause/resume tables, replay a load from the lake, dispatcher care |
| [`runbooks/incident_stale_data.md`](../runbooks/incident_stale_data.md) | Freshness warning/stale alerts — triage from the dead-man's switch to root cause |
| [`runbooks/schema_drift.md`](../runbooks/schema_drift.md) | A table auto-paused on source schema change (DCT-008/010) |
| [`runbooks/backfill.md`](../runbooks/backfill.md) | Reseed/backfill a window or table (new SCN boundary, staged, atomic promote) |
| [`runbooks/rollback.md`](../runbooks/rollback.md) | Roll back a bad load (immutable prior loads, `table_prev`, catalog rebuild) |
| [`runbooks/backup_restore.md`](../runbooks/backup_restore.md) | Backups, quarterly restore drill (`scripts/restore-drill.sh`), DuckDB catalog rebuild |

## 13. Formal acceptance & traceability

- **Acceptance record:** `specs/CHECKLIST.md` — every
  line item marked `[x]` or `[!]`; gates A–H signed; overall verdict
  *approved with documented exceptions*; `[!]` items map 1:1 to the
  exceptions register E1–E7 (`docs/data-platform.md` §10) with Day-0/
  quarter-one closure triggers (CLAUDE §13).
- **Verification:** 356 platform + 122 app + 94 frontend unit offline
  tests (572) + 120+ Playwright E2E; the `ci-pipeline` workflow gates the
  full offline matrix behind one `pipeline-confidence` status check; the
  sample-seed pipeline run (publish → catalog → dual-target dbt build) is
  the end-to-end acceptance exercise.
- **Spec traceability:** checklist ID families map the retired
  specification's sections to implementation — SRC/ORA (source &
  extraction, retired spec §7–10), SEED (§8), INC (§16–17), LAKE/DDB (§5,
  §19), PG/DLT (§15), DBT (§20–21), API/IQ (§22–23), OBS/DQ (§12, §24),
  SEC/IAM (§13), CICD (§25), DR (§26), CUT/BI (§27) — all consolidated
  into this document's §§1–12. The checklist's per-item evidence column is
  the authoritative pointer from requirement to code/test.

---

*This document is the architectural record for v1.0.0 LTS. Amendments
follow the same review path as the checklist: propose → review → update
the decision log → re-mark affected checklist items at the next release.*
