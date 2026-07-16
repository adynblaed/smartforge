-- Staging: deterministic rename/cast/dedupe only; raw meaning preserved (DBT-006).
with latest as (
    {{ latest_by_key(source('omega_raw', 'machines'), ['machine_id']) }}
)
select
    cast(machine_id as bigint)                as machine_id,
    cast(machine_code as varchar)             as machine_code,
    cast(machine_name as varchar)             as machine_name,
    cast(machine_type as varchar)             as machine_type,
    cast(line_code as varchar)                as line_code,
    cast(factory_code as varchar)             as factory_code,
    cast(status as varchar)                   as status,
    cast(rated_output_per_hour as numeric(12, 2)) as rated_output_per_hour,
    cast(commissioned_at as timestamp)        as commissioned_at,
    coalesce(cast(is_decommissioned as boolean), false) as is_decommissioned,
    cast(last_update_ts as timestamp)         as source_updated_at,
    cast(_source_scn as bigint)               as source_scn,
    cast(_load_id as varchar)                 as load_id,
    _extracted_at                             as extracted_at
from latest
where not coalesce(_is_deleted, false)
  and not coalesce(cast(is_decommissioned as boolean), false)
