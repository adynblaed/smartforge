-- Work orders enriched with the platform surrogate identity (work_order_uid,
-- stamped at extraction — DCT-011) and the parent link that drives the
-- genealogy tree (int_work_order_genealogy).
with latest as (
    {{ latest_by_key(source('omega_raw', 'work_orders'), ['work_order_id']) }}
)
select
    cast(work_order_uid as varchar)         as work_order_uid,
    cast(work_order_id as bigint)           as work_order_id,
    cast(parent_work_order_uid as varchar)  as parent_work_order_uid,
    cast(parent_work_order_id as bigint)    as parent_work_order_id,
    cast(machine_id as bigint)              as machine_id,
    cast(wo_number as varchar)              as wo_number,
    cast(title as varchar)                  as title,
    cast(wo_type as varchar)                as wo_type,
    cast(item_no as varchar)                as item_no,
    cast(qty_ordered as numeric(18, 4))     as qty_ordered,
    cast(qty_completed as numeric(18, 4))   as qty_completed,
    cast(status as varchar)                 as status,
    cast(priority as varchar)               as priority,
    cast(current_operation as varchar)      as current_operation,
    cast(sales_order_no as varchar)         as sales_order_no,
    cast(sales_order_line as bigint)        as sales_order_line,
    cast(scheduled_date as timestamp)       as scheduled_at,
    cast(due_date as timestamp)             as due_at,
    cast(completed_at as timestamp)         as completed_at,
    cast(labor_hours as numeric(10, 2))     as labor_hours,
    cast(cost_total as numeric(18, 2))      as cost_total,
    coalesce(cast(is_cancelled as boolean), false) as is_cancelled,
    cast(created_at as timestamp)           as created_at,
    cast(last_update_ts as timestamp)       as source_updated_at,
    cast(_source_scn as bigint)             as source_scn,
    cast(_load_id as varchar)               as load_id,
    _extracted_at                           as extracted_at
from latest
where not coalesce(_is_deleted, false)
  and not coalesce(cast(is_cancelled as boolean), false)
