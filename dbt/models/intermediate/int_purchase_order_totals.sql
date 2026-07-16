-- Reusable line-level rollup joined to POs in fct_purchase_orders.
select
    po_id,
    count(*)                          as line_count,
    sum(qty_ordered)                  as total_qty_ordered,
    sum(qty_received)                 as total_qty_received,
    sum(line_amount)                  as lines_amount
from {{ ref('stg_omega__purchase_order_lines') }}
group by po_id
