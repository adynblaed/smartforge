# Runbook: Stale Data Incident

**Signal:** `/api/v1/platform/freshness` shows `warning`/`stale`, the
Data Platform page shows red freshness, or the freshness alert fired.
Hourly tables: warn 75 min, error 120 min. Daily: warn 26 h, error 30 h.

Architecture context: [`ARCHITECTURE.md`](../specs/ARCHITECTURE.md) §8
(failure handling & self-healing).

## Triage order

0. **One glance at Grafana** — the "Data Platform Pipeline" dashboard:
   time-since-last-run, run success/failure trend, and
   `smartforge_pipeline_scheduler_tick_failures_total` (ticks that died
   before recording a run — invisible in the control tables by
   definition).
1. **Is the scheduler alive?** Check the `platform-worker` service logs
   (`docker compose logs platform-worker`). If dead, restart it — the next
   tick catches up automatically (idempotent loads; the single-flight
   lock is session-scoped and needs no cleanup). Note: an ad hoc
   `POST /platform/sync/run` returning **409** means a pipeline run is
   already in flight — that is healthy behavior, not a fault.
2. **Did a run fail?** `GET /api/v1/platform/replication/runs` or:
   ```sql
   SELECT * FROM control.replication_runs ORDER BY started_at DESC LIMIT 10;
   SELECT * FROM control.replication_table_runs
    WHERE status NOT IN ('succeeded') ORDER BY started_at DESC LIMIT 20;
   ```
   The `error` column names the failing stage.
3. **Oracle connectivity?** The most common cause. Test:
   `uv run python -c "from app.dataplatform.oracle.connection import ping; print(ping())"`
   Check omega listener, credentials expiry, network path, VPN.
4. **Schema drift?** If the error mentions drift, the table paused itself
   on purpose (fail closed, DCT-008). Follow `runbooks/schema_drift.md`.
5. **dbt failure?** Raw data may be fresh while marts are stale (Specs
   §24.3). Fix the model/test and re-run:
   `uv run python -m app.dataplatform.cli dbt`

## Replay without touching Oracle (DR-005)

If Parquet published but the warehouse load failed, do NOT re-extract.
Replay from the lake: the next dispatcher tick retries the merge, or load a
specific published load via a short script against
`app.dataplatform.warehouse.loader.load_published_parquet`.

## Communicate

Stale-but-serving data must be labeled, not hidden: the Data Platform page
and `/platform/freshness` already expose lag. Notify the affected dataset
owners (see `owner` in config/tables.yml) when error thresholds are crossed.
