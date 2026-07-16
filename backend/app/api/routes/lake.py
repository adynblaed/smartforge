"""Data-lake query surface (tag: lake).

Read-only DuckDB access over the published Parquet lake (DDB-003). The
catalog file is opened read_only per request; identifiers resolve from the
DuckDB information schema (an allowlist by construction) and all values are
bound parameters. No client-supplied SQL exists here (API-004). Queries are
execution-bounded and map to HTTP 504 on timeout (DDB-006); every dataset
read emits one telemetry log line without query text or filter values
(OBS-006/OBS-008).
"""

from __future__ import annotations

import datetime as dt
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
                "dataset": f"{r['schema']}.{r['name']}",
                "schema": r["schema"],
                "name": r["name"],
                "engine": "duckdb",
                "type": r["type"],
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
) -> dict[str, Any]:
    if not _catalog_exists():
        raise _lake_unavailable()
    try:
        relations = duckdb_catalog.list_relations()
    except Exception:
        # Safe 503 for the client, full trail for operators (OBS-004).
        logger.exception("lake catalog listing failed for dataset read")
        raise _lake_unavailable() from None
    known = {f"{r['schema']}.{r['name']}": r for r in relations}
    if dataset not in known:
        raise HTTPException(status_code=404, detail="Unknown lake dataset")
    schema, name = dataset.split(".", 1)

    started = time.perf_counter()
    try:
        column_names, _rows = duckdb_catalog.query_readonly(
            f'SELECT * FROM "{schema}"."{name}" LIMIT 0'  # noqa: S608
        )
        columns = set(column_names)
        reserved = {"limit", "offset"}
        filters = {k: v for k, v in request.query_params.items() if k not in reserved}
        invalid = set(filters) - columns
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown filter column(s): {sorted(invalid)}",
            )
        where = ""
        params: list[Any] = []
        if filters:
            where = " WHERE " + " AND ".join(
                f'CAST("{col}" AS VARCHAR) = ?' for col in filters
            )
            params = list(filters.values())

        _cols, count_rows = duckdb_catalog.query_readonly(
            f'SELECT count(*) FROM "{schema}"."{name}"{where}',  # noqa: S608
            params,
        )
        names, rows = duckdb_catalog.query_readonly(
            f'SELECT * FROM "{schema}"."{name}"{where} LIMIT ? OFFSET ?',  # noqa: S608
            [*params, limit, offset],
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
    # or query text (OBS-006/OBS-008).
    logger.info(
        "lake dataset read dataset=%s rows=%d elapsed_ms=%d engine=duckdb "
        "filter_columns=%s request_id=%s",
        dataset,
        len(rows),
        elapsed_ms,
        sorted(filters),
        getattr(request.state, "request_id", "-"),
    )
    return {
        "data": [dict(zip(names, row, strict=True)) for row in rows],
        "count": int(count_rows[0][0]),
        "meta": {
            "dataset": dataset,
            "engine": "duckdb",
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "limit": limit,
            "offset": offset,
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
