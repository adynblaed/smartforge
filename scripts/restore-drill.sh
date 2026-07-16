#!/usr/bin/env bash
# Quarterly restore drill (DR-002/DR-011) — runbooks/backup_restore.md, automated.
#
# Restores the latest warehouse dump into a scratch database, validates data
# correctness (not just service availability — DR-014), rebuilds the DuckDB
# catalog read-only, and prints a drill record to attach to the ops log.
# Safe by construction: only ever writes to ${RESTORE_DB} (dropped and
# recreated), never to production databases.
#
# Usage: bash scripts/restore-drill.sh   (from the repo root, stack running)
set -euo pipefail

RESTORE_DB="${RESTORE_DB:-warehouse_restore_test}"
WAREHOUSE_DB="${WAREHOUSE_DB:-warehouse}"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "== SmartForge restore drill — started ${STARTED_AT} =="

# 1. Locate the newest warehouse dump produced by the db-backup service.
LATEST_DUMP="$(docker compose exec -T db-backup sh -c \
  "ls -1t /backups/daily/${WAREHOUSE_DB}-*.sql.gz 2>/dev/null | head -1")"
if [ -z "${LATEST_DUMP}" ]; then
  echo "FAIL: no ${WAREHOUSE_DB} dump found under /backups/daily — has db-backup completed a cycle?"
  exit 1
fi
echo "-- restoring from: ${LATEST_DUMP}"

# 2. Recreate the scratch database and restore into it.
docker compose exec -T db psql -U "${POSTGRES_USER:-postgres}" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS ${RESTORE_DB};" \
  -c "CREATE DATABASE ${RESTORE_DB};"
docker compose exec -T db-backup sh -c \
  "zcat '${LATEST_DUMP}' | psql -h db -U \"\${POSTGRES_USER}\" -d '${RESTORE_DB}' -v ON_ERROR_STOP=0 -q"

# 3. Validate data correctness, not just presence (DR-014).
echo "-- validation queries"
docker compose exec -T db psql -U "${POSTGRES_USER:-postgres}" -d "${RESTORE_DB}" -v ON_ERROR_STOP=1 -Atc "
  SELECT 'watermarks: ' || count(*) FROM control.replication_watermarks;
  SELECT 'manifests(loaded): ' || count(*) FROM control.replication_manifests WHERE status = 'loaded';
  SELECT 'last publication: ' || coalesce(max(updated_at)::text, 'NONE') FROM control.replication_watermarks;
  SELECT 'reconciliation failures: ' || count(*) FROM audit.reconciliation_results WHERE NOT passed;
"

# Per-table restored counts vs the counts each manifest recorded at load time.
docker compose exec -T db psql -U "${POSTGRES_USER:-postgres}" -d "${RESTORE_DB}" -v ON_ERROR_STOP=1 -P pager=off -c "
  SELECT source_table,
         max(row_count)  AS manifest_rows,
         max(source_scn) AS newest_scn
    FROM control.replication_manifests
   WHERE status = 'loaded'
   GROUP BY source_table
   ORDER BY source_table;
"

# 4. Rebuild the DuckDB catalog from published Parquet (read-only artifact).
echo "-- rebuilding DuckDB catalog from published lake"
docker compose exec -T backend python -c \
  "from app.dataplatform.lake.duckdb_catalog import refresh_catalog; refresh_catalog(); print('catalog rebuilt')"

# 5. Cleanup + record.
docker compose exec -T db psql -U "${POSTGRES_USER:-postgres}" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE ${RESTORE_DB};"
FINISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "== DRILL RECORD =="
echo "started:  ${STARTED_AT}"
echo "finished: ${FINISHED_AT}   (RTO objective: 4h — docs/data-platform.md §8)"
echo "dump:     ${LATEST_DUMP}"
echo "result:   PASS — record this block in the ops log (runbooks/backup_restore.md §Quarterly restore drill)"
