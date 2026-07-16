-- Grain: one row per purchase order, with line rollups.
{{ config(post_hook=["{{ time_series_index('ordered_at') }}"]) }}
select
    p.po_id,
    p.po_number,
    p.supplier_id,
    p.status,
    p.ordered_at,
    p.expected_at,
    p.received_at,
    p.total_amount,
    p.currency_code,
    coalesce(t.line_count, 0)          as line_count,
    t.total_qty_ordered,
    t.total_qty_received,
    t.lines_amount,
    p.load_id,
    p.extracted_at
from {{ ref('stg_omega__purchase_orders') }} p
left join {{ ref('int_purchase_order_totals') }} t
    on t.po_id = p.po_id
