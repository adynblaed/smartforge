select
    customer_id,
    customer_code,
    customer_name,
    segment,
    country_code,
    credit_limit,
    source_updated_at,
    load_id,
    extracted_at
from {{ ref('stg_omega__customers') }}
