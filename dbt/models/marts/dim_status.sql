select
    status_code,
    status_domain,
    description,
    sort_order,
    load_id,
    extracted_at
from {{ ref('stg_omega__status_lookup') }}
