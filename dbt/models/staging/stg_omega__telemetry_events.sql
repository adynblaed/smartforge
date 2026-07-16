-- Append-only event stream (monotonic_append): keys never update, so the
-- dedupe guard only protects against replayed overlap windows.
with latest as (
    {{ latest_by_key(source('omega_raw', 'telemetry_events'), ['event_id']) }}
)
select
    cast(event_id as bigint)          as event_id,
    cast(machine_id as bigint)        as machine_id,
    cast(event_date as timestamp)     as event_date,
    cast(event_ts as timestamp)       as event_at,
    cast(metric_code as varchar)      as metric_code,
    cast(metric_value as numeric(18, 6)) as metric_value,
    cast(unit as varchar)             as unit,
    cast(_source_scn as bigint)       as source_scn,
    cast(_load_id as varchar)         as load_id,
    _extracted_at                     as extracted_at
from latest
where not coalesce(_is_deleted, false)
