with latest as (
    {{ latest_by_key(source('omega_raw', 'purchase_orders'), ['po_id']) }}
)
select
    cast(po_id as bigint)             as po_id,
    cast(po_number as varchar)        as po_number,
    cast(supplier_id as bigint)       as supplier_id,
    cast(status as varchar)           as status,
    cast(order_date as timestamp)     as ordered_at,
    cast(expected_date as timestamp)  as expected_at,
    cast(received_date as timestamp)  as received_at,
    cast(total_amount as numeric(18, 2)) as total_amount,
    cast(currency_code as varchar)    as currency_code,
    coalesce(cast(is_cancelled as boolean), false) as is_cancelled,
    cast(last_update_ts as timestamp) as source_updated_at,
    cast(_source_scn as bigint)       as source_scn,
    cast(_load_id as varchar)         as load_id,
    _extracted_at                     as extracted_at
from latest
where not coalesce(_is_deleted, false)
  and not coalesce(cast(is_cancelled as boolean), false)
