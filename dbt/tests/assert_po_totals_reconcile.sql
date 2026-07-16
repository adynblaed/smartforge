-- Control-total reconciliation (Migration §10.6): PO header total should
-- match the sum of its lines within a cent-level tolerance when lines exist.
select
    p.po_id,
    p.total_amount,
    p.lines_amount
from {{ ref('fct_purchase_orders') }} p
where p.line_count > 0
  and p.total_amount is not null
  and p.lines_amount is not null
  and abs(p.total_amount - p.lines_amount) > 0.05
