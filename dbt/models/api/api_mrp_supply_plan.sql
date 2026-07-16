-- Certified MRP supply plan (API-002/DBT-007): the time-phased view behind
-- the MRP page — one row per item per plan date, rolling demand and supply
-- pegging into a projected running balance, classified against the item
-- master's safety stock. Net inventory rolls forward exactly like the
-- legacy planning sheet: opening on-hand, then day = prior - demand + supply.
with pegging as (

    select * from {{ ref('stg_omega__mrp_pegging') }}

),

-- Current on-hand per item: the 'On Hand Quantity' pegging row carries the
-- opening balance in balance_qty.
opening as (

    select
        item_no,
        sum(coalesce(balance_qty, 0)) as opening_qty
    from pegging
    where source_type = 'On Hand Quantity'
    group by item_no

),

-- One bucket per item per due date: supply rows (Work Order / Purchase
-- Order receipts) vs demand rows (Sales Order / WO Comp. / BOM Comp.).
daily as (

    select
        item_no,
        cast(due_at as date)                             as plan_date,
        sum(case when source_type in ('Work Order', 'Purchase Order')
                 then coalesce(supply_qty, 0) else 0 end) as supply_qty,
        sum(case when source_type in ('Sales Order', 'WO Comp.', 'BOM Comp.')
                 then coalesce(demand_qty, 0) else 0 end) as demand_qty,
        count(case when source_type = 'Work Order'
                   then 1 end)                            as supply_work_orders,
        max(case when exception_desc is not null
                 then exception_desc end)                 as exception_desc
    from pegging
    where source_type <> 'On Hand Quantity'
      and due_at is not null
    group by item_no, cast(due_at as date)

),

running as (

    select
        d.item_no,
        d.plan_date,
        d.supply_qty,
        d.demand_qty,
        d.supply_work_orders,
        d.exception_desc,
        coalesce(o.opening_qty, 0) as opening_qty,
        coalesce(o.opening_qty, 0) + sum(d.supply_qty - d.demand_qty) over (
            partition by d.item_no
            order by d.plan_date
            rows between unbounded preceding and current row
        ) as projected_balance
    from daily d
    left join opening o
        on o.item_no = d.item_no

)

select
    r.item_no || ':' || cast(r.plan_date as varchar) as plan_row_key,
    r.item_no,
    i.description                as item_description,
    i.item_type,
    i.uom,
    r.plan_date,
    r.demand_qty,
    r.supply_qty,
    r.supply_work_orders,
    r.opening_qty,
    r.projected_balance,
    coalesce(i.safety_stock, 0)  as safety_stock,
    i.mrp_lead_time_days,
    case
        when r.projected_balance < 0 then 'shortage'
        when r.projected_balance < coalesce(i.safety_stock, 0) then 'below_safety'
        else 'covered'
    end                          as plan_status,
    r.exception_desc,
    max(r.plan_date) over ()     as plan_horizon_end
from running r
left join {{ ref('stg_omega__inventory_items') }} i
    on i.item_code = r.item_no
