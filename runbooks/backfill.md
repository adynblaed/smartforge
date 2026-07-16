# Runbook: Backfill / Reseed a Table

**When:** watermark state lost, extended outage, schema change requiring
re-seed, or a table's data is suspected wrong beyond repair.

**Principle:** a reseed is a new full seed for one table at a new SCN. It
never mutates published loads (immutability, LAKE-001) — it publishes a new
`snapshot_scn=` partition and replaces the warehouse raw table via dlt.
Architecture context: [`ARCHITECTURE.md`](../specs/ARCHITECTURE.md) §5.

**Single-flight:** `cli seed` takes the pipeline lock (INC-013). If the
hourly dispatcher is mid-tick, the command refuses with "lock held" —
run between ticks, or stop `platform-worker` for large reseeds.

## Procedure

1. **Pause the table** so the hourly dispatcher skips it:
   set `enabled: false` for the table in `config/tables.yml`, commit, deploy.
2. **Coordinate with the omega DBA** if the table is large (SRC-014):
   agree the extraction window before running off-hours.
3. **Re-run discovery** and review the plan (schema may have drifted):
   ```
   cd backend
   uv run python -m app.dataplatform.cli discover
   uv run python -m app.dataplatform.cli plan
   ```
4. **Confirm + seed only that table** (interactive confirmation phrase):
   ```
   uv run python -m app.dataplatform.cli seed --tables OMEGA.WORK_ORDERS
   ```
5. **Verify:** check `control.replication_table_runs` for the run,
   `audit.reconciliation_results` for passing counts, and
   `/api/v1/platform/freshness`.
6. **Rebuild marts:** `uv run python -m app.dataplatform.cli dbt`
7. **Re-enable** the table in `config/tables.yml`.

## Failure mid-seed

A failed seed leaves the previous watermark and previous published loads
untouched. Partial staging files remain under `{LAKE_ROOT}/_staging/` —
inspect, then delete or quarantine them. Re-running the seed produces a new
load_id; nothing needs manual cleanup in Postgres (dlt merge is idempotent).
