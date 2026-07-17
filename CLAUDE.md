# CLAUDE.md — SmartForge Platform Guide

**SmartForge v1.0.0** — Future Form's smart-factory intelligence platform: live
machine telemetry, AI-assisted operations (ForgeAI), a 3D digital twin,
predictive maintenance, ERP/MES integrations, a customer portal, executive
observability, **and a governed analytics data platform** (omega Oracle →
Parquet lake → DuckDB + PostgreSQL warehouse → dbt → FastAPI).

This file is the single entry point for a developer, operator, or AI agent
working in this repository. Everything here is verifiable in-repo; deeper
material is linked, not duplicated.

---

## 1. Repository map

| Path | What lives there |
|---|---|
| `backend/app/` | FastAPI application: routes, models, services, workers |
| `backend/app/dataplatform/` | Analytics platform: Oracle extraction, lake, warehouse, pipeline, CLI |
| `backend/app/api/routes/{platform,warehouse,lake}.py` | Governed data-platform API |
| `backend/tests/` | Template suite (Postgres required, resets users — keep isolated) |
| `backend/tests_smartforge/` | App suite: services + every router, in-memory SQLite, no services needed |
| `backend/tests_dataplatform/` | Data-platform suite: mocked Oracle, real DuckDB/PyArrow in temp dirs |
| `frontend/` | React 19 + TanStack Router/Query + Tailwind v4 + shadcn/ui (route table: `frontend/README.md`) |
| `config/tables.yml` | **Replication contracts** — one reviewed contract per omega table (DCT-001) |
| `config/type_mappings.yml` | Explicit Oracle→Postgres/Arrow/DuckDB type rules (fail-closed) |
| `dbt/` | Transformations: staging → intermediate → marts/api; tests, freshness, exposures, snapshots |
| `sql/` | Warehouse role DDL, Oracle discovery queries (read-only) |
| `orchestration/` | cron / Task Scheduler entry points for the hourly dispatch |
| `QUICKSTART.md` | Operator walkthrough: omega credentials → connection testing → seed rehearsal → initial migration |
| `runbooks/` | Operations: initial migration SOP, stale data, drift, backfill, rollback, backup/restore, support model |
| `docs/` | Architecture, API, data model, deployment, **data-platform handbook** (governance/evidence) |
| `specs/` | The formal record: `ARCHITECTURE.md` (specification of record, consolidating the retired blueprint/spec drafts), `CHECKLIST.md` (marked acceptance), `FEATURES.md` (release feature matrix) |
| `infra/` | Helm chart, Argo CD apps, Prometheus/Grafana, Vault notes |
| `compose.yml` / `compose.override.yml` | Production-shaped stack / dev overrides |

## 2. Prerequisites

- **Docker + Docker Compose** (the whole stack runs in compose)
- **uv** (Python 3.10+; backend deps incl. oracledb/duckdb/dbt/dlt) — `cd backend && uv sync`
- **bun** (preferred) or **npm** for the frontend — `cd frontend && bun install`
- Optional: a reachable **omega Oracle** source with a *dedicated read-only
  account* (never an app-owner or APEX account — ORA-001), and an
  **ANTHROPIC_API_KEY** for real ForgeAI (offline fallback otherwise).

## 3. Install & launch

```bash
cp .env.example .env       # then set real secrets (see §4)
docker compose up --build
```

| URL | Service |
|---|---|
| http://localhost:5173 | App (login: `smartforge@futureform.com` / `futureform2026`) |
| http://localhost:8000/docs | Swagger UI (+ /redoc; every environment, `API_DOCS_ENABLED` kill switch) |
| http://localhost:9090 / :3001 | Prometheus / Grafana (loopback-only) |
| http://localhost:8080 | Adminer |

Local dev outside Docker: `docker compose stop backend && cd backend && fastapi dev app/main.py`
and/or `docker compose stop frontend && cd frontend && bun run dev`
(same ports, everything keeps working — see `development.md`).

Kubernetes: `infra/helm/README.md` (chart) + `infra/argocd/README.md` (GitOps).

## 4. Credentials & connection testing

All credentials are environment-injected; the repo contains **no live
secrets** (SEC-001, enforced by gitleaks in CI). Generate strong values:
`python -c "import secrets; print(secrets.token_urlsafe(32))"`.

Identity model (least privilege, IAM-001..004):

| Identity | Scope | Configured via |
|---|---|---|
| `omega_analytics_reader` | Oracle: CREATE SESSION + SELECT only. **Writes are proven to fail at every connect** (`verify_read_only`) | `OMEGA_ORACLE_*` |
| `warehouse_loader` | Postgres: writes `raw_oracle`, `control`, `audit` only | `WAREHOUSE_LOADER_*` |
| `warehouse_transformer` | Postgres: reads raw, owns `staging`/`intermediate`/`marts`/`api` | `WAREHOUSE_DBT_*` |
| `warehouse_api_reader` | Postgres: SELECT on `marts`/`api`/control views only; API sessions are `READ ONLY` + statement-timeout | `WAREHOUSE_API_*` |
| DuckDB writer | platform-worker only; API opens `read_only=True` | `DUCKDB_PATH` |
| App superuser / internal / customer | FastAPI RBAC (`User.role`) | `FIRST_SUPERUSER*`, seeded accounts |

**Test everything with one command** (deployment health gate, CICD-011):

```bash
cd backend
uv run python -m app.dataplatform.cli preflight                        # strict: fails on anything
uv run python -m app.dataplatform.cli preflight --tolerate-unreachable # sandbox: report-only connectivity
```

Checks: contracts + type mappings validate → production secrets set → lake
paths writable → dbt project present → Oracle reachable **and read-only**
(a writable identity is always fatal) → all three warehouse roles
authenticate → DuckDB catalog opens read-only.

Runtime health: `GET /api/v1/utils/health-check/` (liveness),
`GET /api/v1/platform/health` (data-platform readiness: warehouse, catalog,
lake), `GET /api/v1/platform/freshness` (data currency — the dead-man's
switch: a dead scheduler surfaces as `stale`, never as healthy).

Pipeline performance (OBS-008): every seed/sync/sample run records the
standard migration KPI block — rows, bytes, duration, rows/s, Mbps,
success rate — as one grep-able log line, in the run's control-table
`detail`, and as Prometheus instruments
(`smartforge_pipeline_*`: rows/bytes counters, stage-duration histograms,
last-run gauges) scraped from the platform-worker (`:9108`) and
`GET /api/v1/metrics`; Grafana ships a "Data Platform Pipeline" dashboard.

## 5. Service catalogue

| Service (compose) | Purpose | Scaling rule |
|---|---|---|
| `backend` | FastAPI app + data-platform API (read-only analytics access) | Horizontal (stateless; WS fan-out via Redis) |
| `frontend` | nginx-served React build | Horizontal |
| `db` | PostgreSQL 18: app DB **and** `warehouse` DB (role-separated) | Vertical / managed service |
| `worker` | Telemetry simulator → health scoring → alerts | **Exactly 1** (double-write hazard) |
| `platform-worker` | Hourly ELT dispatcher: extract → lake → warehouse → dbt; Prometheus exporter on `:9108` (pipeline throughput/duration/success KPIs) | **Exactly 1** (DuckDB single-writer, DDB-002; advisory-lock single-flight) |
| `db-backup` | Rotated `pg_dump` of both databases (PG-009) | 1 |
| `redis` | Pub/sub + caching | 1 / managed |
| `qdrant` | ForgeAI vector store | 1 / managed |
| `prestart` | Alembic migrations (runs to completion before backend) | Job |
| `prometheus` / `grafana` | Metrics + dashboards (loopback-only ports) | 1 each |
| `adminer` | DB admin UI (behind Traefik) | 1 |

Traefik (external `traefik-public` network) terminates TLS and applies
coarse per-IP rate-limit + security-header middlewares to the API router
(SEC-005/012/013). Inside the app, a **role-aware limiter**
(`app/core/ratelimit.py`) tiers callers by JWT role claims —
superuser/internal/customer/anonymous-per-IP token buckets, env-tunable
(`RATE_LIMIT_*`), 429 + `Retry-After`, health/metrics/WS exempt (API-017).
Runtime model (logging topology, error handling, caching inventory,
Redis/worker scope): `docs/architecture.md` §Runtime model.

## 6. API surface & contracts

All endpoints live under `/api/v1` (JWT bearer auth; interactive docs at
`/docs` + `/redoc` in every environment, withdrawable via
`API_DOCS_ENABLED=false`). App domains (machines, work orders, quality,
supply chain, customer portal, ForgeAI…) are catalogued in `docs/api.md`;
the frontend route ↔ endpoint map is in `frontend/README.md`.

**Data platform** (typed, versioned, paginated, provenance-stamped):

| Endpoint | Auth | Contract |
|---|---|---|
| `GET /platform/health`, `/freshness`, `/replication/tables`, `/replication/runs`, `/reconciliation` | internal | Observability: contracts, watermarks, runs, reconciliation results |
| `POST /platform/discovery/run`, `GET /platform/seed/plan`, `POST /platform/seed/confirm`, `POST /platform/sync/run` | **superuser** | Mutating ops; seeding requires exact plan fingerprint + confirmation phrase `SEED OMEGA` |
| `GET /warehouse/datasets[/{dataset}]`, `GET /warehouse/kpis` | internal | Certified marts/api schemas only; allowlisted filter grammar `column[__op]=value` (op ∈ eq/neq/gt/gte/lt/lte/contains, values typed + bound) + `order_by`; `READ ONLY` transaction, 15 s statement timeout, `limit ≤ 1000` — serves the Work Orders explorer + MRP page |
| `GET /lake/datasets[/{dataset}]`, `GET /lake/loads` | internal | Exploratory DuckDB views over published Parquet — SAME contract standard as `/warehouse` (canonical `omega.{table}` ids + `version` metadata, `raw_oracle.*` accepted as deprecated alias; identical filter grammar + `order_by`; pagination caps; provenance `meta`); read-only connection, bound parameters, one connection scope per read; manifest provenance ledger |

Contract rules (API-002/003/006/009, DBT-007): request/response schemas are
Pydantic-typed; data values are always bound parameters; identifiers come
from server-side allowlists; every list endpoint paginates with a hard cap;
errors never leak SQL, paths, or stack traces; responses carry `meta`
provenance (engine, generated_at, freshness where applicable). Breaking
changes to `api_*`/mart models require versioning or deprecation with
migration guidance (API-016). Every request carries an `X-Request-ID`
correlation header (API-014).

## 7. Data lifecycles

### 7.1 Operational (transactional app)

```
simulator → telemetry_events → health scoring → machine_health_scores
                    ├─▶ alert rules → alerts → work_orders → Fiix (mock)
                    ├─▶ Redis pub/sub → WebSocket → frontend (live)
                    └─▶ Prometheus gauges → Grafana
```

### 7.2 Analytics ELT (the data platform)

**Seed (once per table, operator-gated):**
`discover` (read-only inference + PK/cursor verification + SCN boundary) →
reviewed **seed plan** persisted with fingerprint → human confirmation
(`SEED OMEGA`) → extract `AS OF SCN` with keyset pagination → **staging** →
row-count validation → **atomic publish** (immutable Parquet + manifest) →
dlt merge into warehouse → schema version recorded → reconciliation
(source/lake/warehouse counts, PK uniqueness) → **watermark committed last**
→ DuckDB catalog refresh. Both stores provably derive from the same
publication (SEED-009).

**Incremental (hourly/daily, scheduler or cron):** drift check (fail-closed
pause per table, DCT-008) → windowed extract (fixed upper bound; overlap on
the lower bound; idempotent merge dedupes) → same publish → load → reconcile
→ watermark-last sequence. Failed stages leave the watermark untouched; the
next tick replays the window safely (INC-004/005). An older load can never
overwrite newer state (SCN guard, INC-006).

**Deletes:** soft-delete columns captured naturally; hard deletes swept by
the weekly key reconciliation (`_is_deleted` soft-mark; dbt staging filters
them out).

**Transform & serve:** `dbt build` runs against **both** targets after each
window; failed critical tests block mart publication (raw stays, marts stay
stale and *visibly* stale). Certified consumption = warehouse `marts`/`api`;
exploratory = lake views (IQ-010).

**Retention:** published snapshots pruned to `LAKE_RETAINED_SNAPSHOTS`
(default 3); backups rotate per `BACKUP_KEEP_*`; control/audit rows retained
with the warehouse (OBS-012).

### 7.3 Invariants (do not break these)

1. Published Parquet is immutable — corrections are a new `load_id`.
2. Watermarks commit only after publish + load + validation succeed.
3. One writer **at a time**: every pipeline writer entry point — dispatcher
   tick, operator CLI seed/sync/reconcile-deletes, superuser API
   seed/sync, and the dev sample seed — runs under one Postgres advisory
   lock (`state.pipeline_lock`, INC-013/DDB-002; concurrent triggers get
   409/skip). Data-serving paths open the stores read-only, always.
4. No contract, no replication — and unmapped Oracle types fail closed.
5. Oracle is read-only, always verified, never load-bearing for serving:
   no *data-serving* endpoint touches Oracle (API-001; replay uses the
   lake, DR-005). The superuser `/platform` control-plane ops (discovery,
   seed, sync) are the deliberate, lock-guarded exception.

## 8. Data exchange & migration procedures

| Task | Procedure |
|---|---|
| **Initial migration (first seed)** | `QUICKSTART.md` (credentials → rehearsal → production seed) governed by the gated SOP `runbooks/initial_migration.md` |
| **Sandbox seed (dev only, no Oracle)** | `cli bootstrap && cli sample-seed` — the real pipeline over the deterministic sample dataset (genealogy + backlog + MRP pegging); refused outside `PLATFORM_ENV=development` |
| **Rehearse a seed safely** | Scratch-store overrides (`WAREHOUSE_DB` + `LAKE_ROOT` + `DUCKDB_PATH`) → bootstrap → discover → `seed --tables …` → verify → tear down — `QUICKSTART.md` Part 2 |
| **Add a table** | Add a reviewed contract to `config/tables.yml` (key, cursor, cadence, delete strategy, classification, owner) → `cli discover` → review plan → `cli seed` → verify freshness + reconciliation |
| **Pause / resume a table** | `enabled: false` (or `cadence: manual`) in its contract; state and data stay intact — `runbooks/operations.md` |
| **Replay a load** | From published Parquet, never Oracle — `runbooks/operations.md` §Replay |
| **Reseed / backfill** | `runbooks/backfill.md` (new SCN boundary, staged, validated, atomic promote) |
| **Roll back a bad load** | `runbooks/rollback.md` (previous immutable loads + `table_prev` semantics) |
| **Schema drift** | Table auto-pauses; follow `runbooks/schema_drift.md` (named responder, contract update, mapped renames — DCT-010) |
| **Backup / restore** | `runbooks/backup_restore.md` (daily dumps, quarterly drill, DuckDB catalog is a rebuild artifact) |
| **CSV exchange (app data)** | Datasources page or `/datasources/export` / `/datasources/import` (auth + validation enforced) |
| **Regenerate frontend SDK** | `curl http://localhost:8000/api/v1/openapi.json -o frontend/openapi.json && cd frontend && bun run generate-client` (template routes; SmartForge routes use the `sf` wrapper) |
| **Ad hoc analytics / EDA** | Start with `api.api_trailing_windows` (standard 3/6/12-month cross-domain rollups on both engines; fct time columns are indexed on Postgres). Then `GET /lake/datasets/{table}` with allowlisted filters, or DuckDB read-only against the catalog; certified numbers come from `/warehouse` |

## 9. Testing

```bash
# Backend — app suite (no services needed; in-memory SQLite)
cd backend && uv run pytest tests_smartforge -q

# Backend — data platform suite (no services needed; mocked Oracle, real DuckDB/Parquet)
cd backend && uv run pytest tests_dataplatform -q

# Backend — template suite (needs Postgres; resets users — CI/compose only)
docker compose exec backend bash scripts/tests-start.sh

# dbt — parse/compile both engines + docs artifacts
cd backend && uv run dbt parse --project-dir ../dbt --profiles-dir ../dbt --target lake
cd backend && uv run dbt parse --project-dir ../dbt --profiles-dir ../dbt --target warehouse

# Frontend — unit (vitest) and E2E (Playwright; stack must be up)
cd frontend && bun run test:unit
cd frontend && bun run test          # or: CI=1 docker compose run --rm -e CI=1 playwright ...
```

What the suites prove: read-only enforcement (Oracle identity, DuckDB
reader, warehouse API role), watermark-last ordering with injected failures
at every stage, idempotent replay + SCN regression refusal, manifest/publish
immutability, schema-drift fail-closed pause, SQL-injection resistance
(bound params + identifier allowlists), authz denial (401/403, superuser
gates), pagination caps, safe error bodies, freshness classification,
dispatcher cadences, seed-confirmation gate — plus the full app-router
matrix in `tests_smartforge` and 120+ Playwright E2E tests.

CI (`.github/workflows/`): **`ci-pipeline`** is the formal offline
pipeline — six parallel gates (backend lint+types, the 356-test platform
suite, the 122-test app suite, frontend biome+tsc+94 vitest tests, dbt
dual-target parse + docs artifact, compose/Helm/preflight contracts)
feeding a single `pipeline-confidence` required status check; zero
external databases. Workflow naming convention: `ci-*` verification,
`cd-*` deploys, `security-*` scanning, `pr-*` PR automation, `chore-*`
housekeeping. Complementary: `ci-backend-db` (template suite vs real
Postgres), `ci-e2e` (Playwright, full stack), `ci-compose-smoke`,
`ci-pre-commit` (ruff, mypy, ty, biome), `ci-coverage` (Smokeshow),
`security-scan` (gitleaks + pip-audit + osv-scanner, weekly cron),
`security-workflow-audit` (zizmor), `security-guard-dependencies`, and
`cd-deploy-{staging,production}` on `main`/release.

## 10. Conventions

- **Python:** ruff + mypy + ty (pre-commit). Docstrings state *purpose and
  constraint*, referencing checklist IDs where a control is implemented
  (e.g. "watermark commits last (INC-005)"). Comments explain *why*, never
  narrate the next line.
- **TypeScript:** biome; file-based routes; nav/breadcrumbs single-sourced
  in `src/components/Sidebar/nav.ts`; SmartForge API calls via `src/smartforge/api.ts`.
- **SQL/dbt:** dialect-neutral models; engine differences isolated in
  macros; every model documented + tested in `schema.yml`; consumers
  registered in `models/exposures.yml`.
- **Secrets:** never in code, config defaults, logs, or errors. `.env` is
  git-ignored; `.env.example` carries placeholders only.
- **Versioning:** semver; v1.0.0 is the current LTS baseline. Release notes
  in `release-notes.md`; the checklist is re-reviewed each major release.
- **Ownership:** `PLATFORM_OWNER_EMAIL` (default `admin@futureform.com`)
  on exposures/alerts; per-dataset owners in `config/tables.yml`.

## 11. Troubleshooting quick reference

| Symptom | Start here |
|---|---|
| Freshness warning/stale | `runbooks/incident_stale_data.md` |
| Table paused (drift) | `runbooks/schema_drift.md` |
| Warehouse load failed, Parquet published | Replay from lake — `runbooks/operations.md` |
| Need last-known-good | `runbooks/rollback.md` / `runbooks/backup_restore.md` |
| Connectivity/credential doubt | `cli preflight` (§4) |
| Who owns / who consumes a dataset | `config/tables.yml` + `dbt/models/exposures.yml` |

## 12. Governance & release record

- **Formal acceptance:** `specs/CHECKLIST.md` — every
  line item marked, gates signed, v1.0.0 recorded; `[!]` items map to the
  exceptions register in `docs/data-platform.md` §10.
- **Feature matrix:** `specs/FEATURES.md` — v1.0.0 features by user
  category (GA / GA* / deferred).
- **Handbook (owners, decisions, risks, SLOs, environments, access
  management):** `docs/data-platform.md`.
- **GDPR & SOC 2 control mapping + data-subject request procedures:**
  `docs/compliance.md` (implemented controls with evidence; formal
  certification is an organizational action, tracked with the sponsor).
- **Specification of record:** `specs/ARCHITECTURE.md` — the ratified
  v1.0.0 LTS architecture (context diagram, component architecture,
  invariants, failure-handling catalogue, decision log D1–D11, runbook
  index, traceability). It consolidates and supersedes the retired
  drafting documents (the migration blueprint and the specs PDF);
  historical "Specs §…"/"Migration §…" citations refer to those drafts.
- **v1.0.0 release notes:** `release-notes.md`.

## 13. Day-0 deployment & go-live testing procedure

The first deployment against the **live** omega source (the retired spec's
§27 procedure, steps 1–16 — consolidated in `specs/ARCHITECTURE.md`).
Work through it in order; each gate must pass before the next step. This
is also the closure path for the open exceptions (E1–E7).

> The hands-on command walkthrough for Phases A–C — DBA grant template,
> connection testing, the mandatory **seed rehearsal** against scratch
> stores, and the production seed — is [`QUICKSTART.md`](QUICKSTART.md),
> governed by the gated SOP
> [`runbooks/initial_migration.md`](runbooks/initial_migration.md) (G0–G7).

**Phase A — Prerequisites (before touching the source)**

1. Signed table inventory confirmed against `config/tables.yml` (schemas,
   PKs, cursors, classification, cadence, owner, delete policy) — Specs §27
   step 1.
2. Oracle read-only identity provisioned by the omega DBA; agree extraction
   windows, session limits, and undo-retention with them (**closes E2**).
3. Secrets injected per environment (no `changethis` anywhere);
   `OMEGA_ORACLE_TLS_ENABLED=true` where the listener supports TLS
   (**closes E1**); volume encryption confirmed on the host/cluster.

**Phase B — Provision & verify (no data movement yet)**

4. `uv run python -m app.dataplatform.cli bootstrap` — creates the
   warehouse DB, 7 schemas, role grants, control tables (idempotent).
5. `uv run python -m app.dataplatform.cli preflight` — **strict mode, must
   exit 0**: proves the Oracle identity is read-only (fatal if writable),
   all three warehouse roles authenticate, lake paths writable, contracts
   valid. Rerun after any credential change.
6. `uv run python -m app.dataplatform.cli discover` — read-only inference;
   review `config/generated/source_catalog.json`, verify every table shows
   `pk_verified` + `cursor_verified`, zero blocking issues. Confirm the
   cursor actually moves for every write path (Specs §10 gotcha:
   "`updated_at` columns lie") with the DBA before seeding.

**Phase C — Initial seed (off-peak, DBA on notice)**

7. `uv run python -m app.dataplatform.cli plan` → review → `cli seed`
   (confirmation phrase `SEED OMEGA`). Watch source load with the DBA
   during the first table; pause between tables if limits are approached.
   Record seed durations — these become the reseed benchmarks
   (**closes SEED-016 part of E3**).
8. Verify: `GET /platform/reconciliation` all-pass;
   `GET /lake/loads` manifests complete; warehouse counts equal manifest
   counts; `dbt build` green on both targets.

**Phase D — Business validation (Specs §27 step 14; closes E7 at cutover)**

9. Business owners compare against the legacy reports: KPI totals, report
   totals, customer/order counts, financial sums, date boundaries,
   representative samples. Record sign-off in checklist §27 and keep the
   parallel-run open for the agreed stabilization window (CUT-002/003,
   BI-004, DQ-013, SRC-009).

**Phase E — Enable schedules gradually (Specs §27 step 15)**

10. Enable contracts lowest-risk-first: lookups → small dimensions →
    append-only facts → timestamp-merged transactional tables → large
    tables → delete reconciliation. One cadence tick between enablements;
    watch `/platform/freshness` and runtimes vs the hourly interval.
11. Capture the first week's latency/throughput baselines (API p95,
    extraction durations, scan sizes) against the SLOs in
    `docs/data-platform.md` §8 (**closes PERF-001/002/003 of E3**).

**Phase F — Steady state (first month)**

12. Run the first restore drill — `bash scripts/restore-drill.sh`
    (automated: restore → validate correctness → catalog rebuild → drill
    record; **closes E4**); adopt the daily/weekly/monthly calendar in
    `runbooks/operations.md`.

**Pending action items (each traces to an exception or backlog entry)**

| # | Item | Trigger / target | Ref |
|---|---|---|---|
| 1 | TLS/wallet + network ACLs to live omega verified; volume encryption evidenced | Day-0 Phase A | E1 |
| 2 | DBA agreement on windows/limits + source-side monitoring correlation | Day-0 Phase A/C | E2 |
| 3 | Performance baselines captured against SLOs (the CI perf-regression lane `tests_dataplatform/test_perf_smoke.py` already runs; extend its budgets with measured baselines — capture them from the `smartforge_pipeline_*` metrics / Grafana "Data Platform Pipeline" dashboard) | First staging soak | E3 |
| 4 | Restore drill executed and recorded (`scripts/restore-drill.sh` automates it) | First quarter | E4 |
| 5 | MFA/JIT for administrators via IdP | IdP integration | E5 |
| 6 | Artifact signing/provenance for release images | Maturity backlog | E6 |
| 7 | Legacy parallel-run + business sign-off; then complete checklist Gate H cutover record | Cutover | E7 |
| 8 | Orchestrator graduation review (worker → Dagster) once >20 tables or DAG dependencies emerge | Backlog | D9 |
| 9 | Quarterly access recertification cycle begins | 2026-10-15 | IAM-015 |
