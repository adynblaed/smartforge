with latest as (
    {{ latest_by_key(source('omega_raw', 'inventory_items'), ['item_id']) }}
)
select
    cast(item_id as bigint)           as item_id,
    cast(item_code as varchar)        as item_code,
    cast(description as varchar)      as description,
    cast(category as varchar)         as category,
    cast(uom as varchar)              as uom,
    cast(qty_on_hand as numeric(18, 4))  as qty_on_hand,
    cast(reorder_point as numeric(18, 4)) as reorder_point,
    cast(safety_stock as numeric(18, 4)) as safety_stock,
    cast(mrp_lead_time_days as bigint) as mrp_lead_time_days,
    cast(min_order_qty as numeric(18, 4)) as min_order_qty,
    cast(item_type as varchar)        as item_type,
    cast(unit_cost as numeric(18, 4)) as unit_cost,
    cast(supplier_id as bigint)       as supplier_id,
    cast(last_update_ts as timestamp) as source_updated_at,
    cast(_source_scn as bigint)       as source_scn,
    cast(_load_id as varchar)         as load_id,
    _extracted_at                     as extracted_at
from latest
where not coalesce(_is_deleted, false)
