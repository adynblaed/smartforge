"""Data-lake query surface (tag: lake).

Read-only DuckDB access over the published Parquet lake (DDB-003). The
catalog file is opened read_only per request (ONE connection scope per
governed read); identifiers resolve from the DuckDB information schema (an
allowlist by construction) and all values are bound parameters. No
client-supplied SQL exists here (API-004). Queries are execution-bounded
and map to HTTP 504 on timeout (DDB-006); every dataset read emits one
telemetry log line without query text or filter values (OBS-006/OBS-008).

Contract parity with /warehouse (one interoperability standard): canonical
dataset ids (`omega.{table}` for the replicated source views, physical
`raw_oracle.{table}` accepted as a deprecated alias, API-016), explicit
`version` metadata, the same `column[__op]=value` filter grammar with
typed binds (IQ-004), `order_by`/`order_dir`, identical pagination caps,
and the same response envelope (`data`/`count`/`meta` with provenance).
"""

from __future__ import annotations

import datetime as dt
import decimal
import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.deps import InternalUser
from app.dataplatform.config import get_platform_settings
from app.dataplatform.lake import duckdb_catalog
from app.dataplatform.lake.manifest import find_manifests
from app.dataplatform.registry import load_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lake", tags=["lake"])

# Canonical id convention (matches /warehouse): the version lives once in
# the URL prefix; replicated source views are addressed as `omega.{table}`
# — the UI-facing name of the legacy source — and carry version metadata.
# The physical `raw_oracle.{table}` spelling keeps resolving (API-016).
_PHYSICAL_SCHEMA = "raw_oracle"
_CANONICAL_SCHEMA = "omega"
_CONTRACT_VERSION = "v1"

# Same operator allowlist as /warehouse (IQ-004), applied to DuckDB types.
_FILTER_OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "contains"}
_COMPARISON_SQL = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
_INTEGER_PREFIXES = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT")
_NUMERIC_PREFIXES = ("DECIMAL", "DOUBLE", "FLOAT", "REAL")
_TEMPORAL_PREFIXES = ("TIMESTAMP", "DATE")


def _canonical_dataset_id(schema: str, name: str) -> str:
    if schema == _PHYSICAL_SCHEMA:
        return f"{_CANONICAL_SCHEMA}.{name}"
    return f"{schema}.{name}"


def _parse_filter_param(key: str) -> tuple[str, str]:
    """Split `column` / `column__op` into (column, operator)."""
    column, sep, op = key.rpartition("__")
    if not sep:
        return key, "eq"
    return column, op


def _typed_bind_value(raw: str, data_type: str, key: str) -> Any:
    """Parse a comparison bind to the catalog column type (422 on mismatch),
    mirroring the /warehouse rule: bad input is a client error, never a
    database error."""
    upper = data_type.upper()
    try:
        if upper.startswith(_INTEGER_PREFIXES) or upper.startswith("U"):
            return int(raw)
        if upper.startswith(_NUMERIC_PREFIXES):
            return decimal.Decimal(raw)
        if upper.startswith(_TEMPORAL_PREFIXES):
            return dt.datetime.fromisoformat(raw)
    except (ValueError, decimal.InvalidOperation):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid value for filter {key!r}: expected {data_type}",
        ) from None
    return raw


def _escape_like(raw: str) -> str:
    """Escape LIKE wildcards so `contains` matches literally (API-003)."""
    return raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_filter_predicates(
    filters: dict[str, str], column_types: dict[str, str]
) -> tuple[list[str], list[Any]]:
    """Validated WHERE fragments + positional binds — the same allowlisted
    grammar as /warehouse, in DuckDB placeholder form."""
    predicates: list[str] = []
    binds: list[Any] = []
    for key, raw_value in filters.items():
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
        if op == "eq":
            predicates.append(f'CAST("{column}" AS VARCHAR) = ?')
            binds.append(raw_value)
        elif op == "neq":
            predicates.append(f'CAST("{column}" AS VARCHAR) <> ?')
            binds.append(raw_value)
        elif op == "contains":
            predicates.append(f"CAST(\"{column}\" AS VARCHAR) ILIKE ? ESCAPE '\\'")
            binds.append(f"%{_escape_like(raw_value)}%")
        else:
            predicates.append(f'"{column}" {_COMPARISON_SQL[op]} ?')
            binds.append(_typed_bind_value(raw_value, column_types[column], key))
    return predicates, binds


def _lake_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(
            "DuckDB lake catalog is not available yet. Seed the platform "
            "first (discovery -> plan review -> confirm)."
        ),
    )


def _catalog_exists() -> bool:
    return get_platform_settings().DUCKDB_PATH.exists()


@router.get("/datasets")
def list_lake_datasets(_: InternalUser) -> dict[str, Any]:
    if not _catalog_exists():
        raise _lake_unavailable()
    try:
        relations = duckdb_catalog.list_relations()
    except Exception:
        logger.exception("duckdb catalog listing failed")
        raise _lake_unavailable() from None
    return {
        "data": [
            {
                "dataset": _canonical_dataset_id(r["schema"], r["name"]),
                "schema": r["schema"],
                "name": r["name"],
                "engine": "duckdb",
                "type": r["type"],
                # Replicated source views are governed v1 contracts
                # (config/tables.yml); other relations carry no version.
                "version": _CONTRACT_VERSION
                if r["schema"] == _PHYSICAL_SCHEMA
                else None,
            }
            for r in relations
        ],
        "count": len(relations),
    }


@router.get("/datasets/{dataset}")
def read_lake_dataset(
    dataset: str,
    request: Request,
    _: InternalUser,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    order_by: str | None = None,
    order_dir: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> dict[str, Any]:
    """Paginated rows from one lake view — the same request/response
    contract as /warehouse/datasets/{dataset}: canonical ids, allowlisted
    `column[__op]=value` filters with typed binds, `order_by`/`order_dir`,
    capped pagination, provenance meta."""
    if not _catalog_exists():
        raise _lake_unavailable()
    try:
        relations = duckdb_catalog.list_relations()
    except Exception:
        # Safe 503 for the client, full trail for operators (OBS-004).
        logger.exception("lake catalog listing failed for dataset read")
        raise _lake_unavailable() from None
    known: dict[str, dict[str, str]] = {}
    for r in relations:
        known[_canonical_dataset_id(r["schema"], r["name"])] = r
        # Deprecated physical alias keeps resolving (API-016).
        known[f"{r['schema']}.{r['name']}"] = r
    if dataset not in known:
        raise HTTPException(status_code=404, detail="Unknown dataset")
    relation_meta = known[dataset]
    schema, name = relation_meta["schema"], relation_meta["name"]
    canonical = _canonical_dataset_id(schema, name)

    started = time.perf_counter()
    try:
        # ONE read-only connection scope (and one execution budget) for the
        # whole governed read: column catalog, count, page.
        with duckdb_catalog.read_scope() as run:
            _cols, type_rows = run(
                """
                SELECT column_name, data_type
                  FROM information_schema.columns
                 WHERE table_schema = ? AND table_name = ?
                 ORDER BY ordinal_position
                """,
                [schema, name],
            )
            column_types = {str(r[0]): str(r[1]) for r in type_rows}

            reserved = {"limit", "offset", "order_by", "order_dir"}
            filters = {
                k: v
                for k, v in request.query_params.items()
                if k not in reserved
            }
            if order_by is not None and order_by not in column_types:
                raise HTTPException(
                    status_code=422, detail="Unknown order_by column"
                )
            where_parts, binds = _build_filter_predicates(
                filters, column_types
            )
            where = (
                f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
            )
            order = (
                f' ORDER BY "{order_by}" {order_dir.upper()}'
                if order_by
                else ""
            )
            relation = f'"{schema}"."{name}"'

            _count_cols, count_rows = run(
                f"SELECT count(*) FROM {relation}{where}",  # noqa: S608
                binds,
            )
            names, rows = run(
                f"SELECT * FROM {relation}{where}{order} "  # noqa: S608
                "LIMIT ? OFFSET ?",
                [*binds, limit, offset],
            )
    except HTTPException:
        raise
    except duckdb_catalog.LakeQueryTimeoutError:
        # Safe, internals-free detail (DDB-006/OBS-006).
        raise HTTPException(
            status_code=504, detail="Lake query exceeded the time limit"
        ) from None
    except Exception:
        logger.exception("lake dataset query failed for %s", dataset)
        raise _lake_unavailable() from None

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    # One telemetry line per read: filter COLUMN NAMES only, never values
    # or query text (OBS-006/OBS-008). Always the canonical id, whichever
    # spelling the client used (consistent logging exchange).
    logger.info(
        "lake dataset read dataset=%s rows=%d elapsed_ms=%d engine=duckdb "
        "filter_columns=%s request_id=%s",
        canonical,
        len(rows),
        elapsed_ms,
        sorted(filters),
        getattr(request.state, "request_id", "-"),
    )
    return {
        "data": [dict(zip(names, row, strict=True)) for row in rows],
        "count": int(count_rows[0][0]),
        "meta": {
            "dataset": canonical,
            "version": _CONTRACT_VERSION
            if schema == _PHYSICAL_SCHEMA
            else None,
            "engine": "duckdb",
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "limit": limit,
            "offset": offset,
            "filters": filters,
            "elapsed_ms": elapsed_ms,
        },
    }


@router.get("/loads")
def list_published_loads(_: InternalUser, table: str | None = None) -> dict[str, Any]:
    """Published load manifests — the lake's provenance ledger (LAKE-004)."""
    settings = get_platform_settings()
    registry = load_registry()
    contracts = list(registry.contracts.values())
    if table is not None:
        contracts = [
            c
            for c in contracts
            if c.qualified_name.upper() == table.upper() or c.destination_name == table
        ]
        if not contracts:
            raise HTTPException(status_code=404, detail="Unknown table")
    loads: list[dict[str, Any]] = []
    for contract in contracts:
        table_dir = contract.lake_table_dir(settings.lake_published_dir)
        for manifest in find_manifests(table_dir)[:20]:
            loads.append(
                {
                    "table": contract.qualified_name,
                    "destination": contract.destination_name,
                    "load_id": manifest.load_id,
                    "scn": manifest.source.get("scn"),
                    "row_count": manifest.extraction.get("row_count"),
                    "file_count": manifest.extraction.get("file_count"),
                    "strategy": manifest.strategy,
                    "status": manifest.status,
                    "published_at": manifest.published_at,
                }
            )
    loads.sort(key=lambda entry: str(entry["load_id"]), reverse=True)
    return {"data": loads, "count": len(loads)}
