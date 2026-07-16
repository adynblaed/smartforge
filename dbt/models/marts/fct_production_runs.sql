-- Grain: one row per production run (explicit grain, Migration §10.2).
{{ config(post_hook=["{{ time_series_index('run_started_at') }}"]) }}
select
    r.run_id,
    r.machine_id,
    r.job_code,
    r.product_code,
    r.run_date,
    r.run_started_at,
    r.run_ended_at,
    r.units_planned,
    r.units_produced,
    r.units_scrapped,
    case
        when coalesce(r.units_produced, 0) + coalesce(r.units_scrapped, 0) > 0
        then cast(r.units_scrapped as numeric(18, 6))
             / (r.units_produced + r.units_scrapped)
    end                                        as scrap_rate,
    case
        when coalesce(r.units_planned, 0) > 0
        then cast(r.units_produced as numeric(18, 6)) / r.units_planned
    end                                        as plan_attainment,
    r.load_id,
    r.extracted_at
from {{ ref('stg_omega__production_runs') }} r
