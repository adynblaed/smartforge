# Runbook: Schema Drift on the Omega Source

**Signal:** a table run fails with "Schema drift detected"; the table is
paused automatically (fail closed, DCT-007/DCT-008). Drift means the
ordered-column fingerprint of the source table no longer matches any hash
in `control.schema_versions`. Architecture context:
[`ARCHITECTURE.md`](../specs/ARCHITECTURE.md) §4.1.

## Respond (named responder: data engineering on-call, OPS-008)

1. **See what changed:**
   ```sql
   SELECT schema_hash, observed_at, columns
     FROM control.schema_versions
    WHERE source_schema = :s AND source_table = :t
    ORDER BY observed_at DESC LIMIT 2;
   ```
   Diff the two `columns` JSON payloads.
2. **Classify** (Specs §18.2):
   - New nullable column → additive, safe. Proceed to step 3.
   - New required column / type narrowed / scale changed / column removed /
     PK changed → stop; involve the table's business owner. A PK change
     requires a full reseed.
   - Rename → map explicitly; do not treat as drop+add without owner
     approval (DCT-010).
3. **Update the contract** if needed (`config/tables.yml`) and the affected
   dbt staging model (`dbt/models/staging/stg_omega__<table>.sql`). If a
   new type appears, add its mapping to `config/type_mappings.yml`.
4. **Re-run discovery** so the new schema hash is recorded and reviewed:
   `uv run python -m app.dataplatform.cli discover`
5. **Resume:** the next sync accepts the newest recorded hash. For breaking
   changes, reseed the table instead (`runbooks/backfill.md`).

Never silently coerce an incompatible change — the pause is the feature.
