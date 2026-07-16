with latest as (
    {{ latest_by_key(source('omega_raw', 'quality_inspections'), ['inspection_id']) }}
)
select
    cast(inspection_id as bigint)     as inspection_id,
    cast(run_id as bigint)            as run_id,
    cast(machine_id as bigint)        as machine_id,
    cast(inspection_date as timestamp) as inspection_date,
    cast(inspected_at as timestamp)   as inspected_at,
    cast(inspector_code as varchar)   as inspector_code,
    upper(cast(result as varchar))    as result,
    cast(defect_count as bigint)      as defect_count,
    cast(last_update_ts as timestamp) as source_updated_at,
    cast(_source_scn as bigint)       as source_scn,
    cast(_load_id as varchar)         as load_id,
    _extracted_at                     as extracted_at
from latest
where not coalesce(_is_deleted, false)
