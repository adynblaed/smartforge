-- Grain: one row per work order, carrying the deterministic surrogate
-- identity and its resolved genealogy (root/depth/path — parent orders
-- split into children and grandchildren; see int_work_order_genealogy).
{{ config(post_hook=["{{ time_series_index('due_at') }}", "{{ time_series_index('created_at') }}"]) }}
select
    w.work_order_uid,
    w.work_order_id,
    w.parent_work_order_uid,
    w.parent_work_order_id,
    g.root_work_order_uid,
    g.root_work_order_id,
    g.genealogy_depth,
    g.genealogy_path,
    g.child_count,
    g.is_leaf,
    w.machine_id,
    w.wo_number,
    w.title,
    w.wo_type,
    w.item_no,
    w.qty_ordered,
    w.qty_completed,
    w.status,
    w.priority,
    w.current_operation,
    w.sales_order_no,
    w.sales_order_line,
    w.scheduled_at,
    w.due_at,
    w.completed_at,
    w.labor_hours,
    w.cost_total,
    (w.completed_at is not null
     or upper(coalesce(w.status, '')) in ('CLOSED', 'COMPLETED', 'DONE'))
                                        as is_closed,
    w.created_at,
    w.load_id,
    w.extracted_at
from {{ ref('stg_omega__work_orders') }} w
left join {{ ref('int_work_order_genealogy') }} g
    on g.work_order_uid = w.work_order_uid
