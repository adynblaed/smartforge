-- Open-order backlog lines (legacy OPEN_ORDERS_BACKLOG report source).
-- Each line carries its own surrogate identity plus the producing work
-- order's UUID (stamped at extraction against the work_orders entity), so
-- the backlog joins the genealogy without string matching (DCT-011).
with latest as (
    {{ latest_by_key(source('omega_raw', 'sales_order_lines'), ['order_no', 'line_no']) }}
)
select
    cast(sales_order_line_uid as varchar) as sales_order_line_uid,
    cast(order_no as varchar)             as order_no,
    cast(line_no as bigint)               as line_no,
    cast(customer_id as bigint)           as customer_id,
    cast(customer_po_no as varchar)       as customer_po_no,
    cast(item_no as varchar)              as item_no,
    cast(item_description as varchar)     as item_description,
    cast(item_type as varchar)            as item_type,
    cast(order_qty as numeric(18, 4))     as order_qty,
    cast(balance_qty as numeric(18, 4))   as balance_qty,
    cast(available_qty as numeric(18, 4)) as available_qty,
    cast(amount_usd as numeric(18, 2))    as amount_usd,
    cast(priority as bigint)              as priority,
    cast(work_order_uid as varchar)       as work_order_uid,
    cast(work_order_id as bigint)         as work_order_id,
    cast(current_operation as varchar)    as current_operation,
    cast(order_date as timestamp)         as ordered_at,
    cast(due_date as timestamp)           as due_at,
    coalesce(cast(is_cancelled as boolean), false) as is_cancelled,
    cast(last_update_ts as timestamp)     as source_updated_at,
    cast(_source_scn as bigint)           as source_scn,
    cast(_load_id as varchar)             as load_id,
    _extracted_at                         as extracted_at
from latest
where not coalesce(_is_deleted, false)
  and not coalesce(cast(is_cancelled as boolean), false)
