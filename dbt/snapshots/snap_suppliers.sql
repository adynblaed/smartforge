{% snapshot snap_suppliers %}
{{
    config(
        target_schema='marts',
        unique_key='supplier_id',
        strategy='timestamp',
        updated_at='source_updated_at',
    )
}}
-- SCD Type 2 history for suppliers (Migration §7.2): rating/ownership
-- changes are business-relevant over time. Other dimensions are explicit
-- Type 1 (see marts/schema.yml descriptions).
select * from {{ ref('stg_omega__suppliers') }}
{% endsnapshot %}
