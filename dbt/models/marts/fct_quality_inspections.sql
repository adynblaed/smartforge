-- Grain: one row per inspection.
{{ config(post_hook=["{{ time_series_index('inspected_at') }}"]) }}
select
    q.inspection_id,
    q.run_id,
    q.machine_id,
    q.inspection_date,
    q.inspected_at,
    q.inspector_code,
    q.result,
    q.result = 'PASS'                  as passed,
    q.defect_count,
    q.load_id,
    q.extracted_at
from {{ ref('stg_omega__quality_inspections') }} q
