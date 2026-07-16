-- Purchase-order pipeline by supplier and status.
select
    s.supplier_id,
    s.supplier_code,
    s.supplier_name,
    s.country_code,
    p.status,
    count(*)                            as po_count,
    sum(p.total_amount)                 as total_amount,
    min(p.ordered_at)                   as oldest_ordered_at,
    max(p.extracted_at)                 as extracted_at
from {{ ref('fct_purchase_orders') }} p
join {{ ref('dim_suppliers') }} s
    on s.supplier_id = p.supplier_id
group by 1, 2, 3, 4, 5
