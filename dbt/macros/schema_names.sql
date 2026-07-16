{#-
  Use the custom schema name verbatim (staging/intermediate/marts/api)
  instead of dbt's default `<target_schema>_<custom>` prefixing, so the
  warehouse schemas match the platform contract (PG-001).
-#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
