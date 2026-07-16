-- Certified open-order backlog contract (API-002/DBT-007): sales-order
-- lines with customer identity and the producing work order's genealogy —
-- the governed replacement for the legacy OPEN_ORDERS_BACKLOG report.
select
    s.sales_order_line_uid,
    s.order_no,
    s.line_no,
    c.customer_name,
    s.customer_po_no,
    s.item_no,
    s.item_description,
    s.item_type,
    s.order_qty,
    s.balance_qty,
    s.available_qty,
    s.amount_usd,
    s.priority,
    s.work_order_uid,
    s.work_order_id,
    g.root_work_order_uid,
    g.genealogy_depth,
    s.current_operation,
    s.ordered_at,
    s.due_at,
    s.load_id,
    s.extracted_at
from {{ ref('stg_omega__sales_order_lines') }} s
left join {{ ref('dim_customers') }} c
    on c.customer_id = s.customer_id
left join {{ ref('int_work_order_genealogy') }} g
    on g.work_order_uid = s.work_order_uid
