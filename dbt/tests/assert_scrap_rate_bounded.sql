-- Non-additive measure sanity: scrap_rate must stay within [0, 1]
-- (Migration §10.2 — flag non-additive measures; DQ-008).
select run_id, scrap_rate
from {{ ref('fct_production_runs') }}
where scrap_rate is not null
  and (scrap_rate < 0 or scrap_rate > 1)
