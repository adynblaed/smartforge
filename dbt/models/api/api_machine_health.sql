-- Stable API contract (DBT-007): breaking changes require versioning.
with runs_30d as (
    select
        machine_id,
        count(*)                        as runs_30d,
        sum(units_produced)             as units_produced_30d,
        avg(scrap_rate)                 as avg_scrap_rate_30d
    from {{ ref('fct_production_runs') }}
    where run_started_at > {{ dbt.dateadd('day', -30, dbt.current_timestamp()) }}
    group by machine_id
),
open_wos as (
    select machine_id, count(*) as open_work_orders
    from {{ ref('fct_work_orders') }}
    where not is_closed
    group by machine_id
)
select
    m.machine_id,
    m.machine_code,
    m.machine_name,
    m.machine_type,
    m.line_code,
    m.factory_code,
    m.status,
    coalesce(r.runs_30d, 0)             as runs_30d,
    coalesce(r.units_produced_30d, 0)   as units_produced_30d,
    r.avg_scrap_rate_30d,
    coalesce(w.open_work_orders, 0)     as open_work_orders,
    m.load_id,
    m.extracted_at
from {{ ref('dim_machines') }} m
left join runs_30d r on r.machine_id = m.machine_id
left join open_wos w on w.machine_id = m.machine_id
