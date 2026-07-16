# SmartForge v1.0.0 — Feature Matrix

The release-defining catalogue of what ships in **v1.0.0 LTS** (2026-07-16),
by user feature category. Every row is wired front to back and covered by
the test matrix in [`CLAUDE.md`](../CLAUDE.md) §9. Formal acceptance:
[`CHECKLIST.md`](CHECKLIST.md); architecture and rationale:
[`ARCHITECTURE.md`](ARCHITECTURE.md) (the specification of record,
consolidating the retired blueprint and spec drafts).

**Status legend** — `GA`: generally available in v1.0.0 · `GA*`: GA against
the sandbox's simulated/mocked source (live-source verification is a Day-0
step, see CLAUDE.md §13) · `Deferred`: intentionally not in v1.0.0
(tracked in the modernization backlog / exceptions register).

---

## 1. Factory Operations (operators, supervisors)

| Feature | What it delivers | Where | Status |
|---|---|---|---|
| Command Center | Executive KPIs, risk panels, global operations view, live machine tiles | `/command-center` · `GET /command-center`, `/factory/kpis` | GA |
| Factory Simulation (3D digital twin) | Interactive React-Three-Fiber factory map with machine deep-links and live state | `/factory-map` | GA |
| Machines console | Live cards, health leaderboard, alert center, scoped SOP deep-links | `/machines` · `GET /machines[/{id}/telemetry\|health]` | GA |
| Live telemetry streaming | Redis pub/sub fan-out to WebSockets (multi-replica safe) | `WS /ws/telemetry` | GA* (simulator source) |
| Machine health scoring | Continuous health scores from telemetry with alert-rule evaluation | `worker` service · `GET /machines/{id}/health` | GA* |
| Logs console | Per-service operational log lines + audit trail view | `/logs` · `GET /logs/*` | GA |

## 2. Maintenance & Reliability (maintenance engineers)

| Feature | What it delivers | Where | Status |
|---|---|---|---|
| Alert center | Rule-generated alerts with acknowledge/resolve lifecycle | `/machines` · `POST /alerts/{id}/acknowledge\|resolve` | GA |
| Work orders | Creation (incl. from alert), approval flow, Fiix CMMS sync | `/work-orders` · `POST /work-orders[/from-alert/{id}\|/{id}/approve\|/{id}/sync-fiix]` | GA (Fiix adapter mocked) |
| Maintenance tickets | Master-detail ticket center: serialized tickets, parts & inventory, SOP guidance, acknowledgement + note trail | `/tickets` · `GET/POST /tickets/*` | GA |
| Predictive maintenance signals | Health degradation → alert → drafted work order pipeline | `worker` → alert rules → WO drafting | GA* |
| SOP library | Chaptered procedures, WYSIWYG editor, deep-linkable anchors | `/sops` · `GET/POST /sops/*` | GA |

## 3. Quality & Production Intelligence (quality engineers, planners)

| Feature | What it delivers | Where | Status |
|---|---|---|---|
| OEE analytics | Availability/performance/quality rollups and trends | `/quality` · `GET /oee`, `/production-trends` | GA |
| Defect & scrap analytics | Inspection results, defect Pareto, scrap-rate tracking | `/quality` · `GET /inspections`, `/defects` | GA |
| Machine configurations | Config baselines with approval workflow | `/optimization` · `GET /machine-configurations` (+`/approve`) | GA |
| Optimization recommendations | Config recommendations with accept/decline decisions | `/optimization` · `GET /recommendations` (+`/{id}/decision`) | GA |
| Capacity what-if & simulation studio | Planning capacity view + scenario simulation | `/optimization` · `GET /planning/capacity`, `POST /planning/simulate` | GA |

## 4. MES & Enterprise Integrations (IT/OT integrators)

| Feature | What it delivers | Where | Status |
|---|---|---|---|
| Integration status board | ERP & MES sync health, event log | `/services`, `/integrations` · `GET /integrations/status\|events` | GA (mock adapters) |
| On-demand sync | Trigger ERP/MES synchronization runs | `POST /integrations/erp/sync`, `/mes/sync` | GA (mock adapters) |
| Incident management | Impact view + root-cause analysis records | `/incidents` · `GET/POST /incidents[/{id}/rca]` | GA |

## 5. Supply Chain & Purchasing (buyers, supply chain)

| Feature | What it delivers | Where | Status |
|---|---|---|---|
| Order tracker | Active purchase orders by order with detail panes | `/order-tracker` · `GET /order-tracker`, `/purchase-orders` | GA |
| Inventory & supplier risk | Stock levels, supplier risk scoring, reorder recommendations | `/supply-chain` · `GET /inventory`, `/suppliers`, `/supply-chain/risks\|reorders` | GA |
| Quotes & intake | Quote builder with branded PDF, job intake + approval | `/quotes` · `GET /quotes`, `POST /quotes/generate`, `POST /jobs[/intake\|/{id}/approve]` | GA |

## 6. Customer Portal (external customers)

| Feature | What it delivers | Where | Status |
|---|---|---|---|
| Order tracking | Customer-scoped order list + live order detail | `/portal`, `/portal/orders/{id}` · `GET /customer/orders[/{id}]`, `WS /ws/orders` | GA |
| Scoped assistant | AI order assistant restricted to the caller's own data | `/portal/ask` · `POST /customer/ask` | GA |
| Escalations | Customer escalation submission + internal response desk | `/portal/ask`, `/escalations` · `POST /customer/escalate`, `/customer/escalations/{id}/respond` | GA |
| Tenant isolation | Every customer query filtered by `customer_id`; customer-safe projections; proven by RBAC tests | route dependencies + `tests_smartforge` | GA |

## 7. ForgeAI — AI Assistance (all internal roles)

| Feature | What it delivers | Where | Status |
|---|---|---|---|
| RAG assistant with citations | Answers grounded in SOPs (authoritative) + Forge Facts (secondary), cited by code/section | `/ask-ai` · `POST /ask-ai/ask` | GA (offline deterministic fallback without `ANTHROPIC_API_KEY`) |
| Machine-scoped ask | Per-machine contextual Q&A | `POST /machines/{id}/ask` | GA |
| Knowledge bases (Forge Facts) | User-authored knowledge CRUD, surfaced as ranked AI sources | `/knowledge-bases` · `GET/POST/PATCH/DELETE /ask-ai/knowledge-bases` | GA |
| Vector retrieval | Qdrant-backed semantic search with graceful fallback | `qdrant` service | GA |
| Natural-language-to-SQL | — | — | **Deferred by policy** (IQ-005: no NL-generated SQL against governed stores) |

## 8. Analytics Data Platform (analysts, data engineering)

| Feature | What it delivers | Where | Status |
|---|---|---|---|
| Replication contracts | One reviewed contract per omega table: key, cursor, cadence, delete strategy, classification, owner; no contract → no replication | `config/tables.yml` (14 tables) | GA |
| Deterministic surrogate UUIDs | Contract-declared UUIDv5 identity columns stamped at extraction (identical in lake + warehouse; reseed/replay-stable; cross-table references reproduce target UUIDs) | `surrogate_uids` in `config/tables.yml` · `app/dataplatform/uids.py` | GA |
| Work-order genealogy | Parent → child → grandchild resolution (root, depth, path, child counts) from stamped UUIDs, recursive dual-target dbt model | `dbt/models/intermediate/int_work_order_genealogy.sql` · `api.api_work_orders` | GA |
| Sales-order backlog + MRP pegging | Legacy report replacements as governed contracts: open-order backlog lines and full-replace MRP regeneration output with control totals | `OMEGA.SALES_ORDER_LINES` · `OMEGA.MRP_PEGGING` | GA |
| Read-only source guarantee | Dedicated Oracle identity, write privileges proven absent at every connect | `oracle/connection.py` `verify_read_only` | GA* (live listener = Day-0) |
| SCN-consistent initial seed | `AS OF SCN` extraction, keyset pagination, explicit Arrow schemas, staged → validated → atomically published | `cli discover/plan/seed` | GA* |
| Operator seed gate | Fingerprinted, reviewable seed plan requiring the `SEED OMEGA` confirmation phrase | `cli seed` · `POST /platform/seed/confirm` | GA |
| Hourly/daily incremental sync | High-watermark windows (fixed upper bound + overlap), idempotent PK merge, watermark-commits-last | `platform-worker` · `cli sync/dispatch` | GA* |
| Hard-delete reconciliation | Weekly key sweep soft-marks vanished rows (`_is_deleted`) | `cli reconcile-deletes` | GA* |
| Immutable Parquet lake | Manifested, versioned, quarantine-separated publications; retention pruning | `LAKE_ROOT` · `lake/parquet.py` | GA |
| DuckDB lake catalog | Read-only views over published Parquet only; memory/thread-bounded | `lake/duckdb_catalog.py` | GA |
| PostgreSQL warehouse | 7 schemas, 4 role-separated identities, staged merge loads, SCN regression guard | `warehouse/` · `cli bootstrap` | GA |
| dbt transformation layer | staging → intermediate → 4 dims + 5 facts + 5 certified api products; dual-target (postgres + duckdb) | `dbt/` | GA |
| dbt quality gates | PK/relationship tests, source freshness, singular reconciliation tests, SCD2 supplier snapshot; failures block mart publication | `dbt build` in dispatcher | GA |
| Lineage & impact analysis | Exposures registering every consumer; dbt docs artifacts in CI | `dbt/models/exposures.yml` | GA |
| Governed warehouse API | Certified marts/api datasets: allowlisted filter grammar (`column[__op]=value`, typed bound values) + order_by, read-only transactions, statement timeout, pagination cap, provenance meta | `GET /warehouse/datasets[/{d}]`, `/warehouse/kpis` | GA |
| Governed lake API | Exploratory DuckDB views: bound parameters, read-only connections, interruptible time-bounded queries (504 on overrun), manifest ledger | `GET /lake/datasets[/{d}]`, `/lake/loads` | GA |
| Trailing-window EDA library | Standard 3/6/12-month cross-domain rollups (production, quality, work orders, purchasing, telemetry) built identically on both engines; the batteries-included first query of every EDA session | `api.api_trailing_windows` | GA |
| Time-series indexes | Every fct time column indexed on PostgreSQL via dbt post-hooks (no-op on DuckDB, whose zone maps prune scans) — trailing-window queries stay bounded at scale | `dbt/macros/time_series.sql` | GA |
| Config zero-drift guard | Test-enforced: `.env.example` values equal code defaults and every tunable knob is documented — drift fails CI | `tests_dataplatform/test_config_drift.py` | GA |
| Data Platform page | Freshness, replication tables, runs, reconciliation, warehouse KPIs, lake manifests — graceful not-provisioned states | `/data-platform` | GA |
| Work Orders explorer | Read-only query builder (fields × operators × values, order, limit) over the certified genealogy contract; provenance/latency footer | `/data-platform` § Work Orders Explorer | GA |
| MRP supply planning page | Time-phased demand/supply/projected-net grid per item per day, shortage + safety-stock highlighting, summary KPIs, client-side what-if | `/mrp` · `api.api_mrp_supply_plan` | GA |
| Sandbox sample seed | Development-only real-pipeline seed from a deterministic in-repo dataset (genealogy, backlog, consistent MRP balances); refused outside development | `cli sample-seed` | GA |
| Log-based CDC / GoldenGate | — | — | **Deferred** (blocked by read-only source; high-watermark chosen — D2) |

## 9. Data Governance & Observability (platform owners, SRE)

| Feature | What it delivers | Where | Status |
|---|---|---|---|
| Freshness dead-man's switch | Per-table lag vs warn/error thresholds computed from committed watermarks — a dead scheduler reads as stale, never healthy | `GET /platform/freshness` · `/data-platform` page | GA |
| Run/load lineage | Every load traceable: run ID → load ID → SCN → manifest → warehouse rows | `control.*` tables · `GET /platform/replication/runs`, `/lake/loads` | GA |
| Reconciliation ledger | Persisted per-run count + PK-uniqueness checks | `audit.reconciliation_results` · `GET /platform/reconciliation` | GA |
| Control-total reconciliation | Numeric fidelity checks on financial/operational columns: Oracle `AS OF SCN` sums vs extracted Parquet vs warehouse rows per load (`control_total:*` checks) | `control_total_columns` in `config/tables.yml` | GA |
| Query telemetry | Per-request `elapsed_ms` in response meta + structured log line (dataset, rows, engine, request ID — never values) | `/warehouse` + `/lake` handlers | GA |
| Pipeline performance KPIs | Prometheus instruments (`smartforge_pipeline_*`: rows/bytes counters, stage-duration histograms, last-run gauges) + per-run migration KPI block (rows, bytes, duration, rows/s, Mbps, success rate) + one summary log line per run; platform-worker scrape endpoint (`:9108`) and Grafana "Data Platform Pipeline" dashboard | `app/dataplatform/metrics.py` · `infra/grafana/dashboards/data-platform-pipeline.json` | GA |
| Unified logging topology | One timestamped format across API/workers/scheduler/CLI, `LOG_LEVEL`-tunable, correlation IDs; degraded dependencies always leave a trail (once-per-outage for Redis) | `app/core/logging_config.py` | GA |
| Intelligent error surfaces | Layered error boundaries (root → shell → route); status-aware titles/hints (429/503/504 vs "likely a bug" for 5xx) with `Reference: <request-id>` for reporting | `frontend/src/smartforge/errors.ts` · `ErrorComponent` | GA |
| Schema-drift protection | Ordered-schema fingerprinting; incompatible drift pauses the table fail-closed | `pipeline/state.py` + `runbooks/schema_drift.md` | GA |
| Metrics & dashboards | Prometheus exporter + Grafana dashboards (loopback-only) | `:9090` / `:3001` | GA |
| Request correlation | `X-Request-ID` on every response, hostile-input safe | app middleware | GA |
| Audit logging | Approvals, AI answers, escalations, config changes, imports/exports | `audit_logs` | GA |

## 10. Administration & Security (admins, security)

| Feature | What it delivers | Where | Status |
|---|---|---|---|
| RBAC | admin / operator / maintenance / planner / customer roles; superuser gates on privileged ops; full-surface anonymous-rejection test sweep | route deps · `test_route_wiring.py` | GA |
| User management | Admin CRUD over users | `/admin` (superuser) | GA |
| Ingress hardening | Traefik TLS, coarse per-IP rate limiting, security headers; app-layer header/host/CORS defenses | `compose.yml` · `app/main.py` | GA |
| Role-aware rate limiting | Per-identity token buckets tiered by JWT role claims (superuser/internal/customer/anonymous-per-IP); 429 + `Retry-After` + `X-RateLimit-*`; health/metrics/WS exempt; env-tunable budgets | `app/core/ratelimit.py` (API-017) | GA |
| Secret hygiene | Env-injected credentials only; known-default passwords refused outside local/development at process start; gitleaks + pip-audit + osv-scanner CI (weekly cron) | `.github/workflows/security-scan.yml` · settings validators | GA |
| Compliance mapping | GDPR article + SOC 2 criteria mapping with data-subject request procedures (access/erasure/restriction) | `docs/compliance.md` | GA (external audit = org action) |
| Scheduled backups | Rotated `pg_dump` of app + warehouse databases; documented restore drill | `db-backup` service · `runbooks/backup_restore.md` | GA (drill = Day-0 follow-up, E4) |
| MFA / JIT admin elevation | — | — | **Deferred** (E5: IdP-dependent) |
| Artifact signing / provenance | — | — | **Deferred** (E6) |

## 11. Developer & Operator Experience

| Feature | What it delivers | Where | Status |
|---|---|---|---|
| One-command stack | Full platform via compose; per-service dev swap-out | `docker compose up --build` | GA |
| Preflight gate | Config/credential/connectivity verification incl. fatal writable-identity check | `cli preflight [--tolerate-unreachable]` | GA |
| Operator CLI | bootstrap · discover · plan · seed · sync · reconcile-deletes · dbt · dispatch · freshness | `python -m app.dataplatform.cli` | GA |
| Guided initial migration | Credential setup, connection testing, mandatory scratch-store **seed rehearsal**, then a single-SCN production seed under a gated SOP (G0–G7 with abort criteria) | `QUICKSTART.md` · `runbooks/initial_migration.md` | GA |
| Runbooks | Initial migration SOP, stale data, drift, backfill, rollback, backup/restore, operations & support model | `runbooks/` | GA |
| Test matrix | 356 platform tests (incl. perf-regression lane, surrogate-UUID, sample-seed, pipeline-metrics, single-flight, and config-drift suites) + 122 app tests (incl. route-wiring security sweep, rate limiting, runtime logging) + 94 frontend unit + 120+ Playwright E2E; all offline-capable except E2E | `backend/tests_*`, `frontend/tests*` | GA |
| CI/CD | `ci-pipeline`: 572 offline tests + lint/type + dbt + compose/Helm/preflight contract gates behind one `pipeline-confidence` required check; plus security scans, E2E, staged deploys | `.github/workflows/ci-pipeline.yml` | GA |
| Kubernetes + GitOps | Helm chart (validated) + Argo CD staging/production apps | `infra/helm/`, `infra/argocd/` | GA |
| Datasources CSV exchange | Read-only table views + validated CSV export/import | `/datasources` · `/datasources/export\|import` | GA |
| Dagster/Airflow orchestration | — | — | **Deferred** (D9 graduation path; worker + advisory lock in v1.0.0) |

---

## Cross-release commitments

- **Certified vs exploratory:** certified figures come only from warehouse
  `marts`/`api` (tested, fresh-checked, owned); lake views are exploratory
  (IQ-010). Both are labeled in API metadata.
- **Compatibility:** the v1.0.0 API surface under `/api/v1` is stable;
  breaking changes ship under a new version prefix with deprecation notice
  (API-016).
- **Deferred items** trace to the exceptions register
  ([`docs/data-platform.md`](../docs/data-platform.md) §10) or the
  modernization backlog (§11) — each has an owner and a re-review trigger.
