-- Certified work-order explorer contract (API-002/DBT-007): the stable,
-- genealogy-enriched view served by GET /warehouse/datasets/api.api_work_orders
-- and the frontend Work Orders explorer. Additive changes only (API-016).
select
    f.work_order_uid,
    f.work_order_id,
    f.wo_number,
    f.parent_work_order_uid,
    f.root_work_order_uid,
    f.genealogy_depth,
    f.genealogy_path,
    f.child_count,
    f.is_leaf,
    f.title,
    f.wo_type,
    f.item_no,
    f.qty_ordered,
    f.qty_completed,
    f.status,
    f.priority,
    f.current_operation,
    f.sales_order_no,
    f.sales_order_line,
    m.machine_code,
    f.scheduled_at,
    f.due_at,
    f.completed_at,
    f.is_closed,
    f.labor_hours,
    f.cost_total,
    f.load_id,
    f.extracted_at
from {{ ref('fct_work_orders') }} f
left join {{ ref('dim_machines') }} m
    on m.machine_id = f.machine_id
