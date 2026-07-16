with latest as (
    {{ latest_by_key(source('omega_raw', 'purchase_order_lines'), ['po_id', 'line_number']) }}
)
select
    cast(po_id as bigint)             as po_id,
    cast(line_number as bigint)       as line_number,
    cast(item_id as bigint)           as item_id,
    cast(qty_ordered as numeric(18, 4))  as qty_ordered,
    cast(qty_received as numeric(18, 4)) as qty_received,
    cast(unit_price as numeric(18, 4))   as unit_price,
    cast(line_amount as numeric(18, 2))  as line_amount,
    cast(order_date as timestamp)     as ordered_at,
    cast(last_update_ts as timestamp) as source_updated_at,
    cast(_source_scn as bigint)       as source_scn,
    cast(_load_id as varchar)         as load_id,
    _extracted_at                     as extracted_at
from latest
where not coalesce(_is_deleted, false)
