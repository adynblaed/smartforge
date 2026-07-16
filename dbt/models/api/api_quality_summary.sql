-- Daily quality rollup per machine.
select
    cast(inspection_date as date)       as quality_date,
    machine_id,
    count(*)                            as inspection_count,
    sum(case when passed then 1 else 0 end) as passed_count,
    cast(sum(case when passed then 1 else 0 end) as numeric(18, 6))
        / nullif(count(*), 0)           as pass_rate,
    sum(defect_count)                   as defect_count,
    max(extracted_at)                   as extracted_at
from {{ ref('fct_quality_inspections') }}
group by 1, 2
