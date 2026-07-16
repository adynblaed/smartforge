# Runbook: Backup & Restore

Covers the two PostgreSQL logical databases (`app`, `warehouse`), the Parquet
lake, and the DuckDB catalog. Objectives (DR-001): RPO ≤ 24 h for warehouse
data (next scheduled backup), RTO ≤ 4 h; the lake and catalog are
deterministically rebuildable, so their effective RPO is the last published
load. Architecture context: [`ARCHITECTURE.md`](../specs/ARCHITECTURE.md) §5, §8.

## What is backed up, and by what

| Asset | Mechanism | Where | Cadence |
|---|---|---|---|
| Postgres `app` + `warehouse` | `db-backup` compose service (`pg_dump`, rotated) | `app-db-backups` volume | `BACKUP_SCHEDULE` (default daily); keep 7d/4w/6m |
| Parquet lake (published + manifests) | Volume snapshot of `app-lake-data` (host/cloud tooling) | operator-managed | With host backup policy |
| DuckDB catalog | **Not backed up** — rebuild artifact | — | Rebuilt from published Parquet |
| Pipeline state (watermarks, runs, manifests) | Inside `warehouse` dump (`control.*`, `audit.*`) | with warehouse backup | daily |
| Config & code | Git (contracts, dbt, roles DDL) | repository | every change |

Production deployments should additionally enable WAL archiving / PITR on
the Postgres host or use a managed database service; the `db-backup` sidecar
is the portable baseline, not a PITR replacement (PG-009).

## Restore: PostgreSQL (DR-002)

```bash
# 1. List archives
docker compose exec db-backup ls /backups/daily

# 2. Restore the warehouse into a scratch database first — never overwrite
#    production without a validated dump.
docker compose exec db-backup /bin/sh -c \
  "zcat /backups/daily/warehouse-<date>.sql.gz | psql -h db -U $POSTGRES_USER -d warehouse_restore_test"

# 3. Validate the restore (data correctness, not just service availability — DR-014):
#    - control.replication_watermarks rows present, max(updated_at) sane
#    - reconciliation: SELECT count(*) FROM raw_oracle.<largest table>;
#      compare against control.replication_table_runs.rows_postgres
#    - roles: \du shows warehouse_loader / warehouse_transformer / warehouse_api_reader
# 4. Promote: repeat against the real database, then re-run
#    `uv run python -m app.dataplatform.cli bootstrap` (idempotent grants)
#    and `uv run python -m app.dataplatform.cli dbt` to rebuild marts.
```

## Restore: lake and catalog (DR-003)

Published Parquet is immutable and manifest-verified, so restoration is
either (a) restore the `app-lake-data` volume snapshot, or (b) deterministic
rebuild:

1. Restore volume → verify manifests: every published load dir must contain
   `manifest.json` whose file list and row counts match the Parquet on disk
   (LAKE-012/DR-006 orphan check).
2. Rebuild the DuckDB catalog from published paths only:
   `uv run python -c "from app.dataplatform.lake.duckdb_catalog import refresh_catalog; refresh_catalog()"`
3. If the volume is lost entirely, replay the warehouse from its own backup
   (raw tables are in the dump) and reseed the lake per `backfill.md` at a
   new SCN boundary. Oracle is only re-queried in this total-loss case.

## Pipeline-state recovery (DR-004)

Watermarks, run history, and manifests live transactionally in
`control.*` inside the warehouse dump. After a restore:

- A watermark **older** than the published lake is safe: the next tick
  re-extracts an already-published window; idempotent merge + the
  load-order guard (SCN regression refusal) make the replay a no-op.
- Never hand-edit a watermark forward; that creates a silent gap. To skip a
  window deliberately, reseed the table (`backfill.md`).
- Locks are Postgres session advisory locks — they vanish with the session;
  no lock cleanup is ever required after a crash (DR-008).

## Quarterly restore drill (DR-011)

The drill is automated — from the repo root with the stack running:

```bash
bash scripts/restore-drill.sh
```

It restores the newest warehouse dump into a scratch database, validates
data correctness (watermarks, loaded manifests, per-table counts vs
manifest counts, reconciliation failures), rebuilds the DuckDB catalog
from published Parquet, drops the scratch database, and prints a drill
record. Then:

1. Compare the printed per-table counts against production; investigate
   any delta.
2. Run one `GET /lake/datasets/<table>` smoke query against the rebuilt
   catalog.
3. Record the drill block, duration (vs 4 h RTO), and remediation owners
   in the ops log; file issues for gaps.
