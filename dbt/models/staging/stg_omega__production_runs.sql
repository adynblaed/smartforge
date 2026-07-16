with latest as (
    {{ latest_by_key(source('omega_raw', 'production_runs'), ['run_id']) }}
)
select
    cast(run_id as bigint)             as run_id,
    cast(machine_id as bigint)         as machine_id,
    cast(job_code as varchar)          as job_code,
    cast(product_code as varchar)      as product_code,
    cast(run_date as timestamp)        as run_date,
    cast(run_started_at as timestamp)  as run_started_at,
    cast(run_ended_at as timestamp)    as run_ended_at,
    cast(units_planned as bigint)      as units_planned,
    cast(units_produced as bigint)     as units_produced,
    cast(units_scrapped as bigint)     as units_scrapped,
    cast(last_update_ts as timestamp)  as source_updated_at,
    cast(_source_scn as bigint)        as source_scn,
    cast(_load_id as varchar)          as load_id,
    _extracted_at                      as extracted_at
from latest
where not coalesce(_is_deleted, false)
