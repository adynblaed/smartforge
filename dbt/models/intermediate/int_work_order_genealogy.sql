-- Work-order genealogy: resolves every work order's position in its
-- parent/child/grandchild tree from the extraction-stamped UUIDs.
--   genealogy_depth  0 = root (top-level) order, 1 = child, 2 = grandchild
--   root_work_order_uid/_id = the top-level order the row descends from
--   genealogy_path   human-readable wo_number chain, root first
-- Dialect-neutral recursive CTE (Postgres + DuckDB, DBT-010); depth is
-- capped so a cyclic source link can never hang a build (fail-visible:
-- rows beyond the cap simply do not appear and the mart count test trips).
with recursive work_orders as (

    select
        work_order_uid,
        work_order_id,
        parent_work_order_uid,
        parent_work_order_id,
        wo_number
    from {{ ref('stg_omega__work_orders') }}

),

-- Roots: no parent, or a parent outside the replicated set (an orphan is
-- treated as its own root rather than silently dropped).
genealogy as (

    select
        c.work_order_uid,
        c.work_order_id,
        c.parent_work_order_uid,
        c.work_order_uid  as root_work_order_uid,
        c.work_order_id   as root_work_order_id,
        0                 as genealogy_depth,
        cast(c.wo_number as varchar) as genealogy_path
    from work_orders c
    left join work_orders p
        on c.parent_work_order_uid = p.work_order_uid
    where c.parent_work_order_uid is null
       or p.work_order_uid is null

    union all

    select
        c.work_order_uid,
        c.work_order_id,
        c.parent_work_order_uid,
        g.root_work_order_uid,
        g.root_work_order_id,
        g.genealogy_depth + 1,
        g.genealogy_path || ' > ' || cast(c.wo_number as varchar)
    from work_orders c
    inner join genealogy g
        on c.parent_work_order_uid = g.work_order_uid
    where g.genealogy_depth < 8

),

children as (

    select
        parent_work_order_uid as work_order_uid,
        count(*)              as child_count
    from work_orders
    where parent_work_order_uid is not null
    group by parent_work_order_uid

)

select
    g.work_order_uid,
    g.work_order_id,
    g.parent_work_order_uid,
    g.root_work_order_uid,
    g.root_work_order_id,
    g.genealogy_depth,
    g.genealogy_path,
    coalesce(c.child_count, 0)      as child_count,
    coalesce(c.child_count, 0) = 0  as is_leaf
from genealogy g
left join children c
    on c.work_order_uid = g.work_order_uid
