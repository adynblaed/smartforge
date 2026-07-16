with latest as (
    {{ latest_by_key(source('omega_raw', 'defects'), ['defect_id']) }}
)
select
    cast(defect_id as bigint)         as defect_id,
    cast(inspection_id as bigint)     as inspection_id,
    cast(machine_id as bigint)        as machine_id,
    cast(defect_code as varchar)      as defect_code,
    cast(severity as varchar)         as severity,
    cast(detected_date as timestamp)  as detected_at,
    cast(disposition as varchar)      as disposition,
    cast(last_update_ts as timestamp) as source_updated_at,
    cast(_source_scn as bigint)       as source_scn,
    cast(_load_id as varchar)         as load_id,
    _extracted_at                     as extracted_at
from latest
where not coalesce(_is_deleted, false)
