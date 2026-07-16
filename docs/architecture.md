# SmartForge Architecture

**SmartForge v1.0.0 LTS.** The analytics data platform's formal
architectural record is [`specs/ARCHITECTURE.md`](../specs/ARCHITECTURE.md);
this document covers the application runtime around it.

SmartForge is built on the FastAPI full-stack template and extended into a
modular smart-factory platform.

## Services (logical)

| Service | Implementation |
|---|---|
| API gateway | FastAPI (`app/api/routes/*`) |
| Machine Intelligence | `app/services/machine_intelligence.py` (health scoring, alert rules, WO drafting) |
| Factory Intelligence | `app/services/factory_intelligence.py` (OEE, vision, scrap analytics) |
| Integrations | `app/services/integrations.py` (ERP/MES sync, Fiix adapter) |
| AskAI (RAG) | `app/services/askai.py` (retrieval + Claude `claude-opus-4-8`) |
| Supply Chain | `app/services/supply_chain.py` (quoting, inventory risk) |
| Observability | `app/exporters/prometheus.py` + `/api/v1/metrics` |
| Worker | `app/workers/telemetry_simulator.py` (telemetry → health → alerts → pub/sub) |

## Data flow

```
simulator ──▶ telemetry_events ──▶ health scoring ──▶ machine_health_scores
                                     │
                                     ├─▶ alert rules ──▶ alerts ──▶ work_orders ──▶ Fiix (mock)
                                     ├─▶ Redis pub/sub ──▶ WebSocket ──▶ frontend (live)
                                     └─▶ Prometheus gauges ──▶ /metrics ──▶ Grafana
```

## Analytics data platform

```
omega Oracle (READ-ONLY, verified) ─extract (AS OF SCN, keyset)─▶ Parquet staging
  ─validate─▶ published lake (immutable + manifest) ─┬─▶ DuckDB catalog (read-only views) ─▶ /api/v1/lake
                                                     └─▶ warehouse raw_oracle (dlt merge)
                                                            └─▶ dbt staging → marts/api ─▶ /api/v1/warehouse
control schema: runs, table runs, watermarks (commit LAST), manifests,
schema versions, seed plans · audit: reconciliation, rejected records
platform-worker: hourly dispatch (advisory-lock single-flight) + dbt build both targets
```

| Component | Implementation |
|---|---|
| Contracts & type rules | `config/tables.yml`, `config/type_mappings.yml` (fail-closed) |
| Extraction | `app/dataplatform/oracle/` (thin driver, read-only proof, keyset pagination) |
| Lake | `app/dataplatform/lake/` (atomic publish, manifests, quarantine, retention) |
| Warehouse | `app/dataplatform/warehouse/` (7 schemas, 4 role-separated identities) |
| Pipeline | `app/dataplatform/pipeline/` (seed, incremental, reconciliation, freshness, dispatcher) |
| Transform | `dbt/` (dual-target, tests + freshness + exposures + SCD2 snapshots) |
| Serving | `app/api/routes/{platform,warehouse,lake}.py` (read-only, paginated, provenance) |
| Operations | `app/dataplatform/cli.py` (preflight/discover/seed/sync/…) + `runbooks/` |

## Frontend

React 19 + TanStack Router/Query + Tailwind v4 + shadcn/ui. The 3D digital twin
(`/factory-map`) uses React Three Fiber + drei with procedural machine models.
Internal pages live under `routes/_layout/`; the customer portal under
`routes/portal/`. A thin typed client (`src/smartforge/api.ts`) calls the API
with the same bearer token as the generated client.

## Runtime model: logging, errors, Redis, workers

**Logging (one topology, every process).** `app/core/logging_config.py`
`setup_logging()` is called by all four entrypoints (API, telemetry worker,
platform scheduler, operator CLI): one timestamped
`%(asctime)s %(levelname)s %(name)s %(message)s` format, level tunable via
`LOG_LEVEL`, third-party noise (httpx et al.) capped at WARNING. Logger
namespaces: `smartforge.*` (app), `app.*` module paths (data platform),
`dataplatform.{scheduler,cli}`. Log lines carry identifiers, counts,
durations, and `request_id` — never query literals, tokens, or row
payloads (OBS-006).

**Error handling (fail loud, degrade safe).** Every degraded dependency
leaves a server-side trail: warehouse/lake 503s, per-KPI degradation,
crypto decrypt fallbacks, and Redis publish outages all log (outages log
once per transition, not per message). Clients get safe bodies with
`X-Request-ID` correlation; the unhandled-exception handler returns a
generic 500 and logs the traceback with the request ID. Worker loops never
die on a bad tick: they log with a consecutive-failure count and back off
exponentially (capped) before retrying.

**Redis — deliberately narrow.** Pub/sub fan-out only:
`smartforge:telemetry` (simulator/manual-telemetry → `/ws/telemetry`) and
`smartforge:orders` (order progress → `/ws/orders`, customer-filtered),
plus the `/services` health ping. Both WS endpoints authenticate the JWT
before serving and close 1008 otherwise. Redis down = realtime degrades to
polling (sockets stay open with keepalives); correctness never depends on
Redis. There is **no Redis cache and no durable queue** — don't assume
one; adding one is a reviewed architectural change.

**Workers & async work.** Exactly two long-running workers, each single
replica by design: `worker` (telemetry → health → alerts) and
`platform-worker` (hourly ELT dispatch behind a Postgres advisory lock).
In-request async work uses FastAPI `BackgroundTasks` only for the
superuser-gated platform operations (seed/sync), whose status is
observable via `control.replication_runs`. Long analytics never run in
request workers — they are materialized by the pipeline and served as
bounded reads (API-020 policy in `docs/api.md`).

**Caching inventory (complete — nothing else caches).** (1) *TanStack
Query* is the only data cache: auth-scoped by construction (cache clears
on logout redirect), per-page `staleTime`/`refetchInterval` (30–60 s on
the Data Platform page), retries tiered by status, and 5xx surfacing to
error boundaries — stale UI is bounded by the refetch interval and always
re-validated. (2) *Process singletons* via `lru_cache` (settings, DB
engines) — configuration is immutable per process; restart to change.
(3) *DuckDB catalog views* are a rebuilt artifact over immutable Parquet —
they cannot serve stale data silently because freshness is computed from
committed watermarks, not file presence. (4) *No server-side result
cache* by policy (API-013): any proxy/client cache key must include
identity, dataset, filters, and pagination. (5) Prometheus gauges refresh
per worker tick. There is no Redis cache (see above).

**Command/query separation (CQRS-flavored).** Analytics *queries* are
bounded, read-only, allowlisted GETs — `READ ONLY` transactions +
statement timeout on PostgreSQL, `read_only=True` + interruptible
watchdog on DuckDB, pagination caps, provenance metadata. Platform
*commands* (discovery, seed confirm, sync) are superuser-gated POSTs with
fingerprint/phrase gates, run asynchronously, and are audited in the
control schema. The two paths never share credentials: readers use
`warehouse_api_reader`/read-only DuckDB; only the loader/worker identities
can write.

## Security (spec §11)

RBAC via `User.role` (`admin/operator/maintenance/planner/customer`) with
`get_current_internal_user` / `get_current_customer_user` dependencies. Customer
routes filter every query by the caller's `customer_id` and use customer-safe
projections. Work-order approvals, AI answers, escalations, and config changes
are written to `audit_logs`.
