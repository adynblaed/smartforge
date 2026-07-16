-- full_replace table: every load replaces the whole set (implicit deletes).
with latest as (
    {{ latest_by_key(source('omega_raw', 'status_lookup'), ['status_code']) }}
)
select
    cast(status_code as varchar)      as status_code,
    cast(status_domain as varchar)    as status_domain,
    cast(description as varchar)      as description,
    cast(sort_order as bigint)        as sort_order,
    cast(_source_scn as bigint)       as source_scn,
    cast(_load_id as varchar)         as load_id,
    _extracted_at                     as extracted_at
from latest
where not coalesce(_is_deleted, false)
