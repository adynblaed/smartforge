-- Daily production rollup per machine (reporting timezone: UTC).
select
    cast(run_date as date)              as production_date,
    machine_id,
    count(*)                            as run_count,
    sum(units_planned)                  as units_planned,
    sum(units_produced)                 as units_produced,
    sum(units_scrapped)                 as units_scrapped,
    case
        when sum(coalesce(units_produced, 0) + coalesce(units_scrapped, 0)) > 0
        then cast(sum(units_scrapped) as numeric(18, 6))
             / sum(units_produced + units_scrapped)
    end                                 as scrap_rate,
    max(extracted_at)                   as extracted_at
from {{ ref('fct_production_runs') }}
group by 1, 2
