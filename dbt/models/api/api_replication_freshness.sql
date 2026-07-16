{{ config(enabled = target.name == 'warehouse') }}
-- Freshness/provenance exposed as a queryable data product (API-012).
-- Warehouse-target only: control tables live in PostgreSQL.
select
    source_schema,
    source_table,
    cursor_column,
    committed_cursor_value,
    committed_source_scn,
    committed_load_id,
    updated_at                          as last_published_at
from {{ source('platform_control', 'replication_watermarks') }}
