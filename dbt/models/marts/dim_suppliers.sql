select
    supplier_id,
    supplier_code,
    supplier_name,
    country_code,
    rating,
    source_updated_at,
    load_id,
    extracted_at
from {{ ref('stg_omega__suppliers') }}
