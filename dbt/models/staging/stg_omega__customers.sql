with latest as (
    {{ latest_by_key(source('omega_raw', 'customers'), ['customer_id']) }}
)
select
    cast(customer_id as bigint)       as customer_id,
    cast(customer_code as varchar)    as customer_code,
    cast(customer_name as varchar)    as customer_name,
    cast(segment as varchar)          as segment,
    cast(country_code as varchar)     as country_code,
    cast(credit_limit as numeric(18, 2)) as credit_limit,
    cast(last_update_ts as timestamp) as source_updated_at,
    cast(_source_scn as bigint)       as source_scn,
    cast(_load_id as varchar)         as load_id,
    _extracted_at                     as extracted_at
from latest
where not coalesce(_is_deleted, false)
