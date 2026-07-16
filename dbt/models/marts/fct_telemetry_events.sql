{{
    config(
        materialized='incremental',
        unique_key='event_id',
        incremental_strategy='delete+insert',
        post_hook=["{{ time_series_index('event_at') }}"],
    )
}}
-- Grain: one row per telemetry event. Incremental: large, append-only
-- (Migration §7.1 — computation cache).
select
    event_id,
    machine_id,
    event_date,
    event_at,
    metric_code,
    metric_value,
    unit,
    load_id,
    extracted_at
from {{ ref('stg_omega__telemetry_events') }}
{% if is_incremental() %}
where extracted_at > (select coalesce(max(extracted_at), '1970-01-01') from {{ this }})
{% endif %}
