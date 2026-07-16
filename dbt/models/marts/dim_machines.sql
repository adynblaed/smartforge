select
    machine_id,
    machine_code,
    machine_name,
    machine_type,
    line_code,
    factory_code,
    status,
    rated_output_per_hour,
    commissioned_at,
    source_updated_at,
    load_id,
    extracted_at
from {{ ref('stg_omega__machines') }}
