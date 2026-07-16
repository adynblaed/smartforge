# Runbook: Rollback a Bad Load

**Principle:** published Parquet is immutable and load-versioned, so
rollback = point consumers at earlier loads and rebuild downstream. Never
edit published files (LAKE-001/SEED-013). Architecture context:
[`ARCHITECTURE.md`](../specs/ARCHITECTURE.md) §5, §8.

## Lake (DuckDB)

1. Identify the bad load: `GET /api/v1/lake/loads?table=OMEGA.ORDERS` or
   read the `manifest.json` files under
   `{LAKE_ROOT}/published/omega/<schema>/<table>/`.
2. Move the bad `load_id=...` directory into `{LAKE_ROOT}/quarantine/`
   (with a `_quarantine_reason.txt`). This is the only sanctioned "removal".
3. Refresh the DuckDB catalog:
   `uv run python -c "from app.dataplatform.lake.duckdb_catalog import refresh_catalog; from app.dataplatform.registry import load_registry; refresh_catalog(load_registry())"`

## Warehouse (PostgreSQL)

Raw tables are PK-merged, so removing one load's effect requires replaying
history without it:

- **Small table:** reseed it (see `runbooks/backfill.md`) — fastest, safest.
- **Large table:** restore from the previous snapshot + increments:
  quarantine the bad load (above), then re-run
  `load_published_parquet` for the remaining loads in load_id order.
- **Marts only affected** (bad transform, raw fine): fix dbt, then
  `uv run python -m app.dataplatform.cli dbt`.

## Watermark

If the bad load also advanced the watermark, reset it to the previous
committed values (visible in `control.replication_table_runs` history):

```sql
UPDATE control.replication_watermarks
   SET committed_cursor_value = :prev_cursor,
       committed_source_scn  = :prev_scn,
       committed_load_id     = :prev_load
 WHERE source_schema = :schema AND source_table = :table;
```

The next incremental window re-extracts from that point; overlap + PK merge
make the replay idempotent (INC-004).
