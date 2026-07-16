{#-
Time-series helpers for the standardized 3/6/12-month query library.

time_series_index(column): post-hook that indexes a mart's time column on
the PostgreSQL warehouse, where trailing-window scans benefit from btree
pruning. Deliberately a no-op on the DuckDB lake target — DuckDB's
columnar zone maps already prune time-range scans, and ART indexes would
only tax the rebuildable catalog (DDB-002).

months_ago(n_expr): dialect-neutral "now minus N months" where N may be a
column/expression (dbt.dateadd only takes literals) — the one primitive
behind every trailing-window aggregate.
-#}

{% macro time_series_index(column) %}
    {% if target.name == 'warehouse' %}
        create index if not exists "ix_{{ this.identifier }}_{{ column }}"
            on {{ this }} ("{{ column }}")
    {% else %}
        select 1
    {% endif %}
{% endmacro %}

{% macro months_ago(n_expr) %}
    {%- if target.type == 'postgres' -%}
        (now() - make_interval(months => cast({{ n_expr }} as integer)))
    {%- else -%}
        (current_timestamp - to_months(cast({{ n_expr }} as integer)))
    {%- endif -%}
{% endmacro %}
