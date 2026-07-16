with latest as (
    {{ latest_by_key(source('omega_raw', 'suppliers'), ['supplier_id']) }}
)
select
    cast(supplier_id as bigint)       as supplier_id,
    cast(supplier_code as varchar)    as supplier_code,
    cast(supplier_name as varchar)    as supplier_name,
    cast(country_code as varchar)     as country_code,
    cast(rating as numeric(5, 2))     as rating,
    cast(last_update_ts as timestamp) as source_updated_at,
    cast(_source_scn as bigint)       as source_scn,
    cast(_load_id as varchar)         as load_id,
    _extracted_at                     as extracted_at
from latest
where not coalesce(_is_deleted, false)
