-- MRP pegging rows (legacy INV_ALLOCATION_SUMMARY report source): omega's
-- planning-engine output. source_type semantics, per the source report:
--   supply  -> 'Work Order' (work_order_id), 'Purchase Order' (po_no)
--   demand  -> 'Sales Order' (order_no), 'WO Comp.' (pegged_work_order_id =
--              the CONSUMING work order), 'BOM Comp.'
--   opening -> 'On Hand Quantity' (balance_qty = current on-hand)
-- full_replace contract: every MRP regeneration replaces the whole plan.
with latest as (
    {{ latest_by_key(source('omega_raw', 'mrp_pegging'), ['pegging_id']) }}
)
select
    cast(mrp_pegging_uid as varchar)       as mrp_pegging_uid,
    cast(pegging_id as bigint)             as pegging_id,
    cast(item_no as varchar)               as item_no,
    cast(source_type as varchar)           as source_type,
    cast(due_date as timestamp)            as due_at,
    cast(pegged_due_date as timestamp)     as pegged_due_at,
    cast(order_by_date as timestamp)       as order_by_at,
    cast(supply_qty as numeric(18, 4))     as supply_qty,
    cast(demand_qty as numeric(18, 4))     as demand_qty,
    cast(balance_qty as numeric(18, 4))    as balance_qty,
    cast(exception_desc as varchar)        as exception_desc,
    cast(work_order_uid as varchar)        as work_order_uid,
    cast(work_order_id as bigint)          as work_order_id,
    cast(pegged_work_order_uid as varchar) as pegged_work_order_uid,
    cast(pegged_work_order_id as bigint)   as pegged_work_order_id,
    cast(order_no as varchar)              as order_no,
    cast(po_no as varchar)                 as po_no,
    cast(status as varchar)                as status,
    cast(priority as bigint)               as priority,
    cast(last_update_ts as timestamp)      as source_updated_at,
    cast(_source_scn as bigint)            as source_scn,
    cast(_load_id as varchar)              as load_id,
    _extracted_at                          as extracted_at
from latest
where not coalesce(_is_deleted, false)
