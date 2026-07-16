-- Certified trailing-window KPI library (API-002/DBT-007): one row per
-- standardized analysis window — 3, 6, and 12 trailing months — with the
-- cross-domain aggregates every EDA session reaches for first. Batteries
-- included: consumers filter `window_months` instead of hand-writing (and
-- mis-bounding) date arithmetic, the same contract builds on BOTH engines
-- (warehouse + lake), and the underlying fct time columns are indexed on
-- PostgreSQL (time_series_index) so these scans stay bounded at scale.
with windows as (

    select 3 as window_months
    union all
    select 6
    union all
    select 12

),

production as (

    select
        w.window_months,
        count(r.run_id)                        as production_runs,
        coalesce(sum(r.units_produced), 0)     as units_produced,
        coalesce(sum(r.units_scrapped), 0)     as units_scrapped,
        avg(r.scrap_rate)                      as avg_scrap_rate,
        avg(r.plan_attainment)                 as avg_plan_attainment
    from windows w
    left join {{ ref('fct_production_runs') }} r
        on r.run_started_at >= {{ months_ago('w.window_months') }}
    group by w.window_months

),

quality as (

    select
        w.window_months,
        count(q.inspection_id)                 as inspections,
        avg(case when q.passed then 1.0 else 0.0 end) as pass_rate,
        coalesce(sum(q.defect_count), 0)       as defects
    from windows w
    left join {{ ref('fct_quality_inspections') }} q
        on q.inspected_at >= {{ months_ago('w.window_months') }}
    group by w.window_months

),

work_orders as (

    select
        w.window_months,
        count(f.work_order_uid)                as work_orders_created,
        sum(case when f.is_closed then 1 else 0 end) as work_orders_closed,
        coalesce(sum(f.cost_total), 0)         as work_order_cost_total,
        avg(f.labor_hours)                     as avg_labor_hours
    from windows w
    left join {{ ref('fct_work_orders') }} f
        on f.created_at >= {{ months_ago('w.window_months') }}
    group by w.window_months

),

purchasing as (

    select
        w.window_months,
        count(p.po_id)                         as purchase_orders,
        coalesce(sum(p.total_amount), 0)       as po_spend
    from windows w
    left join {{ ref('fct_purchase_orders') }} p
        on p.ordered_at >= {{ months_ago('w.window_months') }}
    group by w.window_months

),

telemetry as (

    select
        w.window_months,
        count(t.event_id)                      as telemetry_events
    from windows w
    left join {{ ref('fct_telemetry_events') }} t
        on t.event_at >= {{ months_ago('w.window_months') }}
    group by w.window_months

)

select
    win.window_months,
    p.production_runs,
    p.units_produced,
    p.units_scrapped,
    p.avg_scrap_rate,
    p.avg_plan_attainment,
    q.inspections,
    q.pass_rate,
    q.defects,
    wo.work_orders_created,
    wo.work_orders_closed,
    wo.work_order_cost_total,
    wo.avg_labor_hours,
    pu.purchase_orders,
    pu.po_spend,
    t.telemetry_events
from windows win
left join production p on p.window_months = win.window_months
left join quality q on q.window_months = win.window_months
left join work_orders wo on wo.window_months = win.window_months
left join purchasing pu on pu.window_months = win.window_months
left join telemetry t on t.window_months = win.window_months
