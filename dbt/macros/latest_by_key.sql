{#-
  Deduplicate a raw relation to the newest version of each key, ordered by
  _source_scn (then _extracted_at). Dialect-neutral: window functions work
  identically on PostgreSQL and DuckDB, keeping shared models portable
  (Specs §19.4, DBT-010).

  On the warehouse target raw rows are already merged by PK (dlt), so this
  is a no-op guard; on the lake target the raw views union the snapshot and
  every increment, so dedup here is what makes staging correct.
-#}
{% macro latest_by_key(relation, key_columns) %}
select * from (
    select
        r.*,
        row_number() over (
            partition by {{ key_columns | join(', ') }}
            order by r._source_scn desc, r._extracted_at desc
        ) as _dedupe_rank
    from {{ relation }} r
) ranked
where _dedupe_rank = 1
{% endmacro %}
