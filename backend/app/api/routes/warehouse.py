"""Warehouse data products (tag: warehouse).

Serves curated marts and api views from the PostgreSQL warehouse through
the read-only `warehouse_api_reader` role. Guardrails (Checklist API-*):
  * datasets resolve against an allowlist discovered from the `marts` and
    `api` schemas only — clients never supply raw identifiers (API-003);
  * every request runs in a READ ONLY transaction with a statement timeout
    (API-007/008);
  * pagination is mandatory with a hard page-size cap (API-006);
  * filters use a fixed operator allowlist (eq/neq/gt/gte/lt/lte/contains)
    on allowlisted columns; values are always bound parameters and typed
    against the catalog's column type — never interpolated (IQ-004/API-003);
  * responses carry provenance metadata (API-012);
  * every governed read emits one telemetry log line with elapsed time and
    the request correlation id — never query text or filter values
    (OBS-006/OBS-008/IQ-013).
"""

from __future__ import annotations

import datetime as dt
import decimal
import logging
import time
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query, Request

from app.api.deps import InternalUser
from app.dataplatform.config import get_platform_settings
from app.dataplatform.warehouse.postgres import api_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/warehouse", tags=["warehouse"])

_ALLOWED_SCHEMAS = ("marts", "api")

# Query-builder operator allowlist (IQ-004). Filter params are `column`
# (equality) or `column__op`; anything else is rejected with 422.
_FILTER_OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "contains"}
_COMPARISON_SQL = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
_INTEGER_TYPES = {"smallint", "integer", "bigint"}
_NUMERIC_TYPES = {"numeric", "real", "double precision", "money"}
_TEMPORAL_PREFIXES = ("timestamp", "date")


def _parse_filter_param(key: str) -> tuple[str, str]:
    """Split `column` / `column__op` into (column, operator)."""
    column, sep, op = key.rpartition("__")
    if not sep:
        return key, "eq"
    return column, op


def _typed_bind_value(raw: str, data_type: str, key: str) -> Any:
    """Parse a comparison bind to the catalog column type (422 on mismatch).

    Binding a typed Python value keeps the SQL free of casts and makes bad
    input a client error instead of a database error.
    """
    try:
        if data_type in _INTEGER_TYPES:
            return int(raw)
        if data_type in _NUMERIC_TYPES:
            return decimal.Decimal(raw)
        if data_type.startswith(_TEMPORAL_PREFIXES):
            return dt.datetime.fromisoformat(raw)
    except (ValueError, decimal.InvalidOperation):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid value for filter {key!r}: expected {data_type}",
        ) from None
    # Everything else compares as text (explicit, lexicographic).
    return raw


def _escape_like(raw: str) -> str:
    """Escape LIKE wildcards so `contains` matches literally (API-003)."""
    return raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_filter_predicates(
    filters: dict[str, str], column_types: dict[str, str]
) -> tuple[list[str], dict[str, Any]]:
    """Validated WHERE fragments + binds for the allowlisted filter grammar."""
    predicates: list[str] = []
    binds: dict[str, Any] = {}
    for i, (key, raw_value) in enumerate(filters.items()):
        column, op = _parse_filter_param(key)
        if column not in column_types:
            raise HTTPException(
                status_code=422, detail=f"Unknown filter column: {column!r}"
            )
        if op not in _FILTER_OPS:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown filter operator {op!r}; "
                f"allowed: {sorted(_FILTER_OPS)}",
            )
        bind = f"f_{i}"
        if op == "eq":
            predicates.append(f'"{column}"::text = :{bind}')
            binds[bind] = raw_value
        elif op == "neq":
            predicates.append(f'"{column}"::text <> :{bind}')
            binds[bind] = raw_value
        elif op == "contains":
            predicates.append(f'"{column}"::text ILIKE :{bind}')
            binds[bind] = f"%{_escape_like(raw_value)}%"
        else:
            predicates.append(f'"{column}" {_COMPARISON_SQL[op]} :{bind}')
            binds[bind] = _typed_bind_value(raw_value, column_types[column], key)
    return predicates, binds


def _warehouse_unavailable() -> HTTPException:
    """503 with a safe body — and ALWAYS a server-side log trail (OBS-004):
    a degraded dependency must never be invisible to operators."""
    logger.warning("warehouse unavailable for API request", exc_info=True)
    return HTTPException(
        status_code=503,
        detail="Analytics warehouse is not reachable or not built yet.",
    )


def _discover_datasets() -> dict[str, dict[str, Any]]:
    """Allowlist: every relation in marts/api, with its columns."""
    settings = get_platform_settings()
    engine = api_engine()
    with engine.connect() as connection:
        # Same guardrails as every governed read (API-007/008): transaction
        # mode is set FIRST (it must precede any query in the transaction),
        # then the statement timeout bounds the catalog scan.
        connection.execute(sa.text("SET TRANSACTION READ ONLY"))
        connection.execute(
            sa.text(f"SET statement_timeout = {settings.API_STATEMENT_TIMEOUT_MS}")
        )
        rows = connection.execute(
            sa.text(
                """
                SELECT table_schema, table_name, column_name, data_type
                  FROM information_schema.columns
                 WHERE table_schema = ANY(:schemas)
                 ORDER BY table_schema, table_name, ordinal_position
                """
            ),
            {"schemas": list(_ALLOWED_SCHEMAS)},
        ).fetchall()
    datasets: dict[str, dict[str, Any]] = {}
    for schema, table, column, data_type in rows:
        key = f"{schema}.{table}"
        entry = datasets.setdefault(
            key, {"schema": schema, "name": table, "columns": []}
        )
        entry["columns"].append({"name": column, "type": data_type})
    return datasets


@router.get("/datasets")
def list_datasets(_: InternalUser) -> dict[str, Any]:
    try:
        datasets = _discover_datasets()
    except Exception:
        raise _warehouse_unavailable() from None
    return {
        "data": [
            {
                "dataset": key,
                "schema": value["schema"],
                "name": value["name"],
                "engine": "postgres",
                "certified": value["schema"] == "api",
                "column_count": len(value["columns"]),
            }
            for key, value in sorted(datasets.items())
        ],
        "count": len(datasets),
    }


@router.get("/datasets/{dataset}")
def read_dataset(
    dataset: str,
    request: Request,
    _: InternalUser,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    order_by: str | None = None,
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> dict[str, Any]:
    """Paginated rows from one allowlisted mart/api view.

    Filters are query params on allowlisted columns: `column=value` for
    equality, or `column__op=value` with op in eq/neq/gt/gte/lt/lte/contains,
    e.g. /warehouse/datasets/api.api_work_orders?status=open&due_at__lte=2026-08-01
    """
    settings = get_platform_settings()
    try:
        datasets = _discover_datasets()
    except Exception:
        raise _warehouse_unavailable() from None

    if dataset not in datasets:
        raise HTTPException(status_code=404, detail="Unknown dataset")
    meta = datasets[dataset]
    column_names = {c["name"] for c in meta["columns"]}
    column_types = {c["name"]: c["type"] for c in meta["columns"]}

    reserved = {"limit", "offset", "order_by", "order_dir"}
    filters: dict[str, str] = {
        k: v for k, v in request.query_params.items() if k not in reserved
    }
    if order_by is not None and order_by not in column_names:
        raise HTTPException(status_code=422, detail="Unknown order_by column")

    where_parts, binds = _build_filter_predicates(filters, column_types)
    where = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
    order = f' ORDER BY "{order_by}" {order_dir.upper()}' if order_by else ""
    relation = f'"{meta["schema"]}"."{meta["name"]}"'
    binds.update({"limit": limit, "offset": offset})

    engine = api_engine()
    started = time.perf_counter()
    try:
        with engine.connect() as connection:
            # Order matters: SET TRANSACTION READ ONLY must be the first
            # statement of the (autobegun) transaction; the statement
            # timeout has no such restriction and follows it.
            connection.execute(sa.text("SET TRANSACTION READ ONLY"))
            connection.execute(
                sa.text(f"SET statement_timeout = {settings.API_STATEMENT_TIMEOUT_MS}")
            )
            total = connection.execute(
                sa.text(f"SELECT count(*) FROM {relation}{where}"),  # noqa: S608
                binds,
            ).scalar()
            rows = (
                connection.execute(
                    sa.text(
                        f"SELECT * FROM {relation}{where}{order} "  # noqa: S608
                        "LIMIT :limit OFFSET :offset"
                    ),
                    binds,
                )
                .mappings()
                .all()
            )
    except HTTPException:
        raise
    except Exception:
        logger.exception("warehouse dataset query failed for %s", dataset)
        raise _warehouse_unavailable() from None

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    # One telemetry line per read: filter COLUMN NAMES only, never values
    # or query text (OBS-006/OBS-008/IQ-013).
    logger.info(
        "warehouse dataset read dataset=%s rows=%d elapsed_ms=%d engine=postgres "
        "filter_columns=%s request_id=%s",
        dataset,
        len(rows),
        elapsed_ms,
        sorted(filters),
        getattr(request.state, "request_id", "-"),
    )
    return {
        "data": [dict(r) for r in rows],
        "count": int(total or 0),
        "meta": {
            "dataset": dataset,
            "engine": "postgres",
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "limit": limit,
            "offset": offset,
            "filters": filters,
            "elapsed_ms": elapsed_ms,
        },
    }


@router.get("/kpis")
def warehouse_kpis(request: Request, _: InternalUser) -> dict[str, Any]:
    """Small curated KPI block from api views, when they exist."""
    settings = get_platform_settings()
    engine = api_engine()
    started = time.perf_counter()
    kpis: dict[str, Any] = {}
    queries = {
        "production_runs_30d": "SELECT count(*) FROM marts.fct_production_runs "
        "WHERE run_started_at > now() - interval '30 days'",
        "open_work_orders": "SELECT count(*) FROM marts.fct_work_orders "
        "WHERE NOT is_closed",
        "machines_tracked": "SELECT count(*) FROM marts.dim_machines",
        "quality_pass_rate_30d": "SELECT round(avg(CASE WHEN passed THEN 1 ELSE 0 END) * 100, 1) "
        "FROM marts.fct_quality_inspections "
        "WHERE inspected_at > now() - interval '30 days'",
        "open_backlog_value": "SELECT round(sum(amount_usd), 2) "
        "FROM api.api_open_order_backlog",
        "mrp_items_short": "SELECT count(DISTINCT item_no) "
        "FROM api.api_mrp_supply_plan WHERE plan_status = 'shortage'",
    }

    def _arm_transaction_guards(connection: Any) -> None:
        # READ ONLY must be the first statement of the transaction; the
        # timeout follows. Re-armed after every rollback, because rollback
        # ends the guarded transaction and the next statement autobegins
        # a fresh, otherwise-unguarded one.
        connection.execute(sa.text("SET TRANSACTION READ ONLY"))
        connection.execute(
            sa.text(f"SET statement_timeout = {settings.API_STATEMENT_TIMEOUT_MS}")
        )

    try:
        with engine.connect() as connection:
            _arm_transaction_guards(connection)
            for key, query in queries.items():
                try:
                    kpis[key] = connection.execute(sa.text(query)).scalar()
                except Exception:
                    # Degrade per-KPI (a missing mart must not blank the
                    # block) but leave a trail — silent nulls hide outages.
                    connection.rollback()
                    _arm_transaction_guards(connection)
                    kpis[key] = None
                    logger.warning("warehouse kpi %s unavailable", key, exc_info=True)
    except Exception:
        raise _warehouse_unavailable() from None
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "warehouse dataset read dataset=%s rows=%d elapsed_ms=%d engine=postgres "
        "filter_columns=%s request_id=%s",
        "warehouse.kpis",
        len(kpis),
        elapsed_ms,
        [],
        getattr(request.state, "request_id", "-"),
    )
    return {
        "kpis": kpis,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "meta": {"engine": "postgres", "elapsed_ms": elapsed_ms},
    }
