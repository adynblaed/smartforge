# SmartForge Data Platform Handbook (v1.0.0 LTS)

Governance, accountability, and operating record for the omega-Oracle →
Parquet lake → DuckDB + PostgreSQL warehouse analytics platform. This
document is the evidence index referenced by
[`specs/CHECKLIST.md`](../specs/CHECKLIST.md)
and is version-controlled with the platform (DOC-012).

- **Release:** v1.0.0 (2026-07-15)
- **Architecture blueprint:** [`specs/ARCHITECTURE.md`](../specs/ARCHITECTURE.md)
- **Operations:** [`runbooks/`](../runbooks/) · **Contracts:** [`config/tables.yml`](../config/tables.yml)

---

## 1. Ownership & accountability (DOC-001/002, OPS-001)

| Area | Accountable owner | Backup |
|---|---|---|
| Executive sponsor / decision authority | Future Form VP Engineering (`PLATFORM_OWNER_EMAIL`, default `admin@futureform.com`) | COO |
| Source (omega Oracle) | omega DBA team | Data Platform Engineering |
| Pipeline (extract/load/state) | Data Platform Engineering | Backend Engineering |
| Warehouse (PostgreSQL) | Data Platform Engineering | SRE |
| Lake (Parquet + DuckDB) | Data Platform Engineering | Analytics |
| API (FastAPI /platform /warehouse /lake) | Backend Engineering | Data Platform Engineering |
| BI / marts semantics | Analytics + per-domain owners (`owner:` in `config/tables.yml`) | Data Platform Engineering |

Escalation route: on-call → engineering lead → executive sponsor
(`runbooks/operations.md` §Support model). Business meaning and quality
acceptance belong to the domain owners, not the platform team (GOV-008).

## 2. Scope, purpose, and system-of-record boundary (DOC-003/004/005)

- **Approved scope:** the 14 omega tables contracted in `config/tables.yml`
  (schema `OMEGA`; approved schemas listed in `OMEGA_ORACLE_SCHEMAS`).
  Objects without a contract cannot be replicated — the pipeline fails
  closed (DCT-001). APEX applications, PL/SQL packages, and non-tabular
  assets are **explicitly excluded** from this analytical platform
  (SRC-018, CUT-010) and tracked on the modernization backlog (§11).
- **System of record:** omega Oracle remains authoritative for all
  replicated data until a formally approved cutover changes that
  designation. The platform is **analytical replication**, not
  transactional replacement; no write path to Oracle exists anywhere in
  the codebase (ORA-002/003 enforced by `verify_read_only()` at every
  discovery/seed).
- **Purpose limitation (GOV-002):** replicated data serves BI, analytics,
  and operational observability for Future Form manufacturing. Any new use
  requires data-owner approval recorded here.

## 3. Environments & promotion (DOC-006, CICD-013)

| Environment | Stack | Credentials | Promotion |
|---|---|---|---|
| development | `docker compose` local; `PLATFORM_ENV=development` | `.env` (developer-local; `.env.example` template, no live secrets) | feature branch |
| staging | compose or Helm (`values-staging.yaml`); `ENVIRONMENT=staging` | environment secrets (GitHub Environments / Vault) | merge to `main` → `deploy-staging` workflow |
| production | Helm chart + Argo CD (`infra/helm`, `infra/argocd`); `ENVIRONMENT=production` | environment secrets only; distinct Oracle/warehouse identities per env | release publish → `deploy-production` workflow |

Storage separation: each environment owns its `LAKE_ROOT`, `DUCKDB_PATH`,
and warehouse database. `PLATFORM_ENV=production` additionally forces
seed confirmation gates (`SEED_REQUIRE_CONFIRMATION`). Production cannot
inherit development credentials: every credential is environment-injected
and validated at startup (SEC-001).

## 4. Decision log (DOC-008) — ratified 2026-07-15

Decisions D1–D9 from the blueprint (§16) are **ratified as implemented**:

| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | ELT (not ETL/"migration") | Ratified | dlt loads raw; dbt transforms in-target |
| D2 | Query-based high-watermark + reconcile | Ratified | `pipeline/incremental.py`, `pipeline/reconcile_deletes.py` |
| D3 | Parquet interchange | Ratified | `lake/parquet.py`; both stores consume the same publication (SEED-009) |
| D4 | DuckDB lake engine (Parquet-canonical, stateless catalog) | Ratified | `lake/duckdb_catalog.py`; catalog is a rebuild artifact |
| D5 | PostgreSQL warehouse | Ratified | `warehouse/postgres.py` (7 schemas, 4 role-separated identities) |
| D6 | dlt for EL | Ratified | `warehouse/loader.py` (merge on PK, replace for full_replace) |
| D7 | dbt for T (dual-target) | Ratified | `dbt/` project, `warehouse` + `lake` targets |
| D8 | `oracledb` thin mode | Ratified | `oracle/connection.py` (no Instant Client) |
| D9 | Scheduler: worker now, Dagster later | Ratified | `scheduler.py` + advisory-lock single-flight; graduation criteria in §9 of the blueprint |
| D10 | **No in-run retry storms** — failed windows retry at the next schedule tick via idempotent replay (watermark unmoved) | Ratified 2026-07-15 | `pipeline/state.py` watermark commit-last; bounded by one attempt per tick per table (INC-014, ORA-012) |
| D11 | **RLS not required** — single-tenant internal analytics; row/column control via schema+role separation and classification-based exclusion at extraction | Ratified 2026-07-15 | §7 below (IAM-007, PG-014) |

Rejected alternatives (log-based CDC, GoldenGate, triggers, materialized
view logs, Data Pump as load format) and their rationale are recorded in
blueprint §3 and ORA-015.

## 5. Risk register (DOC-009)

| ID | Risk | Owner | Mitigation | Residual |
|---|---|---|---|---|
| R1 | `updated_at` cursor misses a write path → silent gaps | Data Eng | Cursor validation at discovery; overlap window; weekly key reconciliation; change-volume visibility | Low |
| R2 | Hard deletes invisible to incremental | Data Eng | Per-contract delete strategy; `reconcile_deletes.py` weekly sweep; documented staleness window | Low |
| R3 | Source overload from extraction | omega DBA | Pool ≤ 4, call timeout 900 s, keyset chunking, off-peak seeds, schedule-tick (not in-run) retry | Low |
| R4 | Schema drift corrupts downstream | Data Eng | Ordered-schema fingerprint; fail-closed pause per table (DCT-007/008); drift runbook | Low |
| R5 | Watermark state loss | SRE | State transactional in `control.*`; included in daily dumps; older-watermark replay is a safe no-op | Low |
| R6 | DuckDB multi-writer corruption | Data Eng | Single `platform-worker` (compose comment + Helm `Recreate`, replicas 1); advisory lock; API opens read-only | Low |
| R7 | Credential leakage | Security | env-injected secrets, gitleaks CI, no secrets in repo/logs; rotation §7 | Low |
| R8 | Warehouse/lake divergence | Data Eng | Single Parquet publication feeds both; per-run reconciliation persisted to `audit.reconciliation_results` | Low |
| R9 | Sandbox → real-omega transition assumptions | Data Eng | Exceptions register §10 names every control that must be re-verified against the live source | Medium |

## 6. Naming, glossary, classification (DOC-011, SRC-017, GOV-001)

- **Vocabulary:** blueprint §2 (ELT, high-watermark, medallion, SCD…).
- **Layer naming:** `raw_oracle` (bronze) → `staging`/`intermediate`
  (silver) → `marts`/`api` (gold). dbt models: `stg_omega__*`, `int_*`,
  `dim_*`/`fct_*`, `api_*`. Lake paths:
  `published/<schema>/<table>/{snapshot_scn=…|increment_date=…}/load_id=…`.
- **Identifiers:** Oracle UPPERCASE folded to snake_case on landing;
  reserved-word and collision handling in `registry.py` naming rules
  (DCT-011). Metadata columns are the 7 standardized `_source_*`,
  `_load_id`, `_extracted_at`, `_is_deleted` fields (DCT-012).
- **Classification:** every contract carries `classification`
  (internal/confidential) in `config/tables.yml`; unsupported/sensitive
  Oracle types and columns are excluded at extraction (data minimization,
  GOV-003). No regulated PII is in approved scope; if scope changes, the
  classification triggers masking design **before** extraction (GOV-014).

## 7. Access management (IAM-010…018, ORA-016, GOV-005)

- **Identities:** distinct per function — `omega_analytics_reader`
  (Oracle, SELECT-only), `warehouse_loader`, `warehouse_transformer`,
  `warehouse_api_reader` (PostgreSQL), DuckDB writer (platform-worker
  only) vs read-only API connections, app superuser vs internal vs
  customer roles in FastAPI.
- **Joiner/mover/leaver:** access is granted only through these role
  grants (`sql/postgres_roles.sql`); humans get time-boxed membership in
  the matching role, revoked on role change; service credentials rotate by
  replacing the env-injected secret — no code change or outage
  (IAM-011/012).
- **Recertification:** quarterly review of Oracle grants
  (`sql/oracle_inventory.sql` session-privs query), Postgres role
  membership, and app superusers; recorded in the ops log (IAM-015,
  ORA-016).
- **Break-glass:** emergency superuser access = temporary secret issued
  from the secret store, logged in `audit_logs`, revoked and rotated after
  use; reviewed at the next ops review (IAM-016).
- **Separation of duties:** pipeline changes require PR review
  (`CODEOWNERS`/branch protection); the operator confirming a seed
  (`SEED OMEGA` phrase, recorded with `confirmed_by`) is authenticated and
  audited, and cannot self-approve the contract change that introduced it
  (IAM-017).
- **Row-level security:** not required (D11). The warehouse is
  single-tenant internal analytics; the API role can only read `marts`,
  `api`, and read-only control/audit views. If multi-tenant exposure is
  ever added, RLS policies with positive/negative tests become a P0
  precondition (IAM-007, PG-014).
- **Sensitive-access audit:** API request logs carry identity + dataset;
  every load/run/manifest is attributable via run ID; app-level actions
  land in `audit_logs` (GOV-005, OBS-005).
- **Regulatory mapping:** GDPR articles and SOC 2 criteria are mapped to
  these controls, with data-subject request procedures, in
  [`docs/compliance.md`](compliance.md).

## 8. Service-level objectives (OBS-010, PERF-003)

| Objective | Target | Measured by |
|---|---|---|
| Hourly table freshness | warn 75 min / error 120 min | `pipeline/freshness.py` thresholds (env-tunable) |
| Daily table freshness | warn 26 h / error 30 h | same |
| API availability | 99.5% monthly | health checks + Prometheus |
| Warehouse endpoint latency | p95 < 500 ms at 25 concurrent readers | statement timeout 15 s hard cap; Grafana |
| Lake query bound | 15 s timeout, memory-limited DuckDB | `DUCKDB_MEMORY_LIMIT`/`DUCKDB_THREADS` |
| Reconciliation | 0 unexplained count drift per run | `audit.reconciliation_results` |
| Backup RPO / restore RTO | ≤ 24 h / ≤ 4 h | `runbooks/backup_restore.md` |

Freshness is computed from **committed watermarks**, so a dead scheduler
degrades to `stale` — it can never present as healthy (dead-man's switch,
DQ-014).

## 9. Consistency & certification (IQ-010/011, GOV-012)

- **Certified:** `marts` and `api` schemas in the warehouse — tested
  (unique/not-null/relationships/singular tests), fresh-checked, owned,
  and contract-protected. Served by `/api/v1/warehouse/*`.
- **Exploratory:** `raw_oracle` DuckDB views over the lake, served by
  `/api/v1/lake/*` with explicit `engine` provenance in every response
  (IQ-003). Not for certified reporting.
- Consumers see snapshot-consistent raw data per load (single SCN
  boundary for seeds); marts rebuild after each load window, so
  cross-table skew is bounded by one cadence tick and documented here.

## 10. Exceptions register (DOC-010)

Every checklist item marked `[!]` traces to a row here. Approval authority:
executive sponsor. Review: quarterly.

| Exc | Checklist items | Rationale | Compensating control | Expires / re-review |
|---|---|---|---|---|
| E1 | ORA-005, ORA-006 (network path + TLS/wallet to live omega), SEC-003 (at-rest encryption of deployed volumes) | No live omega Oracle or production hosts are reachable from this repository; listener ACLs, TLS/wallet config, and volume-encryption evidence exist only in the target deployment | Read-only identity enforced in code at every connect; TLS supported via `OMEGA_ORACLE_TLS_ENABLED`; encryption + firewall prerequisites documented in `deployment.md` / `infra/helm/README.md` | First production connect |
| E2 | ORA-014 (DBA-side resource monitoring), SRC-014 (extraction-window agreement), SRC-015 (explain-plan review on live source) | Requires the live omega estate and its DBA team | Bounded pool (≤4), 900 s call timeout, keyset (never OFFSET) extraction, per-run telemetry in `control.replication_table_runs`; proposed limits pre-documented in `.env.example` | First production connect |
| E3 | PERF-001/002/003 (representative workload tests), PERF-006 (Parquet sizing benchmark), SEED-016 (seed-duration benchmark) | No production-scale source in sandbox | Hard resource bounds enforced everywhere (timeouts, pagination, memory limits); per-run/per-load timings recorded in the control schema; a perf-regression smoke lane runs in CI (`tests_dataplatform/test_perf_smoke.py`, CICD-014 closed) | First staging soak |
| E4 | DR-002/DR-011 execution (live restore drill) | Docker engine unavailable in the authoring environment; procedure documented and fully automated | `db-backup` sidecar + one-command drill (`scripts/restore-drill.sh`: restore → correctness validation → catalog rebuild → drill record) per `runbooks/backup_restore.md` | First quarterly drill |
| E5 | IAM-009 (MFA/JIT for administrators) | Identity-provider integration is deployment-specific | Superuser-gated mutating endpoints, short-lived JWTs, audit logging of privileged actions | IdP integration |
| E6 | SEC-015 (artifact signing/provenance) | Registry/signing infra not yet selected | Pinned-SHA actions, pinned deps (uv.lock/bun.lock), reproducible images | Platform maturity backlog |
| E7 | SRC-009 (legacy report baselines), CUT-002/003, BI-004, DQ-013 (parallel-run against legacy reports, business-owner sign-off on real figures) | Requires the live legacy reports and named business owners | Reconciliation framework + baseline capture queries ready (`sql/oracle_inventory.sql`, `audit.reconciliation_results`); sign-off table in checklist §27 awaits real cutover | Cutover gate H |

## 11. Modernization backlog (CUT-014)

APEX read-path replacement (this platform) is live; remaining: APEX
write-path/workflow modernization, PL/SQL business-logic port, source
decommission decision (blueprint Open Q #13), Dagster graduation,
MotherDuck/object-store lake tier evaluation (LAKE-016), artifact signing
(E6).

## 12. Review cadence

The platform adopts checklist §29 verbatim; owners per §1. The full
checklist is re-reviewed before any major release and at least annually.
