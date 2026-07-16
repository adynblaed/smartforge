# Runbook: Operations & Support Model

The operating handbook for day-2 operation of the SmartForge data platform.
Day-1 (first seed) is a separate gated SOP: `initial_migration.md` with the
`QUICKSTART.md` walkthrough. Architectural record:
[`ARCHITECTURE.md`](../specs/ARCHITECTURE.md). Companion runbooks: `backfill.md`
(reseed/replay), `rollback.md`, `schema_drift.md`,
`incident_stale_data.md`, `backup_restore.md`.

**Single-flight everywhere (INC-013):** every writer entry point —
dispatcher tick, `cli seed`/`sync`/`reconcile-deletes`,
`POST /platform/seed/confirm` and `/platform/sync/run`, and the dev
`sample-seed` — runs under one Postgres advisory lock. An operator trigger
during a dispatcher tick gets a clean refusal (CLI "lock held" / API
**409**), never an overlap; retry after the running pipeline finishes.
The lock is session-scoped: it vanishes with the session, so no cleanup is
ever needed after a crash.

## Support model (OPS-001)

| Role | Responsibility | Identity |
|---|---|---|
| Platform on-call | First response for pipeline, API, and freshness incidents | Data Platform Engineering (`PLATFORM_OWNER_EMAIL`) |
| Oracle/DBA contact | Source-side sessions, resource limits, undo retention | omega DBA team |
| Data owners | Business meaning, quality acceptance, reconciliation sign-off | `owner` field per table in `config/tables.yml` |
| Escalation | Unresolved Sev-1/Sev-2 after 60 min | Engineering lead → executive sponsor |

Every dataset's accountable owner is recorded in `config/tables.yml`
(`owner`) and on dbt exposures (`dbt/models/exposures.yml`). Support access
uses the read-only `warehouse_api_reader` / DuckDB read-only connections —
troubleshooting never requires loader or transformer credentials (OPS-013).

## Incident severity (OPS-006)

| Severity | Definition | Examples | Response target |
|---|---|---|---|
| Sev-1 | Data exposure or wrong data served as certified | Sensitive column visible to unauthorized role; mart totals wrong | Immediate; page on-call; stop publication (`enabled: false`) |
| Sev-2 | Platform outage or all tables stale past error threshold | Scheduler dead > 2 h; warehouse unreachable | 1 business hour |
| Sev-3 | Single table stale/paused (drift, failed run) | One contract paused fail-closed | Next business day |
| Sev-4 | Degraded performance, noisy alerts | Slow lake scans | Planned work |

Wrong-but-available data is treated as more severe than missing data:
consumers can see staleness (freshness metadata), but not incorrectness —
involve the business data owner on every Sev-1/Sev-2 data-quality incident
(OPS-009).

## Pause one table safely (OPS-003)

Pausing is contract-scoped configuration; it never affects other tables and
never mutates state:

1. Edit `config/tables.yml`: set `enabled: false` on the table (or change
   `cadence: manual` to keep it loadable ad hoc only).
2. Redeploy/restart `platform-worker` (config is read per dispatch).
3. The table's watermark, published Parquet, and warehouse rows remain
   intact. Freshness for the table will go stale — expected and visible.
4. Resume by restoring `enabled: true`; the next tick extracts from the
   committed watermark forward (idempotent overlap handles the gap).

Schema drift pauses a table automatically (fail closed, DCT-008); see
`schema_drift.md` for the named-responder review flow (OPS-008).

## Replay one load safely (OPS-004)

Replays consume the already-published Parquet — Oracle is never re-queried
for a completed extraction (DR-005):

1. Identify the load: `GET /api/v1/lake/loads` or
   `control.replication_manifests`.
2. Re-apply to the warehouse via the loader (merge is idempotent; the
   load-order guard refuses SCN regression):
   `uv run python -m app.dataplatform.cli sync --table <name>` retries the
   pending window, or replay a specific manifest per `backfill.md`.
3. Verify: `GET /api/v1/platform/reconciliation` shows the new comparison.

## Reseed one table safely (OPS-005)

Full procedure in `backfill.md` (discovery → reviewed plan → confirmation
phrase → staged publish → validation → atomic promote → rollback path in
`rollback.md`).

## Routine maintenance calendar (OPS-011)

| Task | Cadence | How |
|---|---|---|
| Freshness & failed-runs review | Daily | Data Platform page / `GET /platform/freshness` |
| Pipeline KPI review (throughput, durations, success rate, tick failures) | Daily | Grafana "Data Platform Pipeline" dashboard (`smartforge_pipeline_*`) |
| Rejected records & reconciliation review | Daily | `audit.rejected_records`, `audit.reconciliation_results` |
| Security alerts & privileged activity | Daily | `security-scan` workflow + `audit_logs` |
| Lake snapshot pruning | Automatic | `LAKE_RETAINED_SNAPSHOTS` (default 3) |
| Backup verification & restore drill | Quarterly | `backup_restore.md` |
| Schema-drift & contract-change review | Weekly | `schema_drift.md`, `config/tables.yml` history |
| Postgres vacuum/bloat/statistics check | Weekly | `pg_stat_user_tables`, autovacuum defaults + swap-based loads |
| Dependency & upgrade review | Monthly | Dependabot PRs; upgrade lanes below |
| Access recertification | Quarterly | `docs/data-platform.md` §Access management |
| DR exercise | Annual | `backup_restore.md` + `rollback.md` findings recorded |

## Dependency upgrades (OPS-012)

Oracle driver, SQLAlchemy, dlt, PyArrow, DuckDB, dbt, and FastAPI are pinned
in `backend/pyproject.toml` + `uv.lock`. Upgrade procedure: bump in a branch →
CI runs `tests_dataplatform` (mocked Oracle + real DuckDB/PyArrow), both dbt
target parses, and the app suites → verify DuckDB storage-format
compatibility note in the release notes of the new version before merging
(DDB-008). Never upgrade DuckDB and republish the catalog in the same change.

## Operational dashboards (OPS-010)

- **Data Platform page** (`/data-platform`): freshness, runs, reconciliation,
  manifests — the first stop for any data incident.
- **Grafana** (`localhost:3001`): infrastructure health (API latency, worker
  liveness) plus the **Data Platform Pipeline** dashboard — last-run
  migration KPIs (rows, bytes, duration, rows/s, bandwidth, success
  ratio), per-stage p95 durations, run success/failure trends, and
  scheduler tick failures, scraped from the platform-worker (`:9108`) and
  the API `/api/v1/metrics`. Platform health ≠ data health: a green infra
  dashboard with red freshness is a data incident, not a false alarm
  (OBS-011).
- **Control schema**: `control.replication_runs`, `control.replication_table_runs`,
  `control.replication_manifests`, `control.replication_watermarks` are the
  queryable source of truth for every run and load ID (OBS-001/002).

## Known limitations (OPS-015)

- Hard deletes on `updated_at_merge` tables surface only after the weekly
  key reconciliation (documented staleness window per contract).
- The lake serves exploratory queries; certified figures come from the
  warehouse marts (IQ-010).
- DuckDB catalog rebuilds are single-writer; ad hoc heavy scans during a
  rebuild may briefly queue.
- Natural-language-to-SQL is not exposed by the platform APIs (IQ-005) —
  ForgeAI answers from its own RAG corpus, never from ad hoc SQL.
