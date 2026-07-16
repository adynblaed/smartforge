"""Hourly/daily incremental synchronization (Specs §16, Checklist INC-*).

Commit sequence per table:
  1. read committed lower watermark
  2. capture source upper boundary + SCN (fixed window, INC-002)
  3. extract [lower - overlap, upper) with keyset pagination
  4. publish Parquet load + manifest
  5. dlt-merge into raw_oracle (idempotent, PK-keyed)
  6. refresh DuckDB catalog views
  7. reconcile window counts
  8. commit new watermark  <- only reached when everything above succeeded
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from app.dataplatform import metrics
from app.dataplatform.config import get_platform_settings
from app.dataplatform.lake import parquet as lake_parquet
from app.dataplatform.lake.duckdb_catalog import refresh_catalog
from app.dataplatform.lake.manifest import LoadManifest
from app.dataplatform.oracle.connection import oracle_connection
from app.dataplatform.oracle.extractor import build_arrow_schema, extract_batches
from app.dataplatform.oracle.metadata import infer_table
from app.dataplatform.oracle.snapshot import capture_boundary
from app.dataplatform.pipeline import reconciliation, state
from app.dataplatform.registry import (
    Registry,
    SyncStrategy,
    TableContract,
    load_registry,
    load_type_mappings,
)
from app.dataplatform.warehouse.loader import load_published_parquet

logger = logging.getLogger(__name__)


def _parse_cursor(value: str | None, cursor_type: str) -> Any:
    if value is None:
        return None
    if cursor_type == "integer":
        return int(value)
    return dt.datetime.fromisoformat(value)


def _lower_bound(contract: TableContract, committed: Any) -> Any:
    """Apply the overlap window to protect against late-arriving rows."""
    if committed is None:
        return None
    if (
        contract.cursor_type == "integer"
        or contract.strategy is SyncStrategy.monotonic_append
    ):
        return committed
    return committed - dt.timedelta(minutes=contract.overlap_minutes)


def sync_table(contract: TableContract, run_id: str) -> dict[str, Any]:
    """One incremental window for one table. Raises on failure; the
    committed watermark is untouched unless every step succeeds."""
    settings = get_platform_settings()
    mappings = load_type_mappings()

    with oracle_connection() as connection:
        # Schema drift check BEFORE extraction (DCT-007: fail closed).
        inferred = infer_table(connection, contract, mappings)
        if not inferred.columns:
            raise RuntimeError(
                f"{contract.qualified_name} is not visible to the extraction account"
            )
        drift = state.record_schema_version(
            contract,
            inferred.schema_hash,
            [c.model_dump() for c in inferred.columns],
        )
        if drift:
            raise RuntimeError(
                f"Schema drift detected on {contract.qualified_name}; table "
                "paused pending review (see runbooks/schema_drift.md)."
            )

        boundary = capture_boundary(connection)
        watermark = state.get_watermark(contract)
        committed = _parse_cursor(watermark.cursor_value, contract.cursor_type)
        lower = _lower_bound(contract, committed)
        upper: int | dt.datetime | None

        if contract.strategy is SyncStrategy.full_replace:
            lower, upper = None, None
        elif contract.cursor_type == "integer":
            upper = _max_source_cursor(connection, contract)
            lower = committed if committed is not None else 0
        else:
            upper = boundary.source_timestamp_utc.replace(tzinfo=None)
            if lower is None:
                lower = dt.datetime(1970, 1, 1)

        state.record_table_run(
            run_id,
            boundary.load_id,
            contract,
            status="extracting",
            source_scn=boundary.scn,
            cursor_lower=str(lower) if lower is not None else None,
            cursor_upper=str(upper) if upper is not None else None,
        )

        schema = build_arrow_schema(inferred)
        started_at = dt.datetime.now(dt.timezone.utc)
        batches = extract_batches(
            connection,
            inferred,
            boundary,
            lower_watermark=lower,
            upper_watermark=upper,
            use_flashback=False,  # incremental windows use cursor bounds
        )
        # Times the Oracle window read + Parquet staging together (the
        # extraction stream is consumed inside write_staged_load).
        with metrics.stage_timer(contract.destination_name, "extract_stage"):
            staging_dir, write_result = lake_parquet.write_staged_load(
                batches,
                schema,
                load_id=boundary.load_id,
                table_name=contract.destination_name,
            )
            lake_parquet.validate_staged_load(staging_dir, write_result.row_count)

    manifest = LoadManifest(
        load_id=boundary.load_id,
        run_id=run_id,
        source={
            "database": contract.source_database,
            "schema": contract.source_schema,
            "table": contract.source_table,
            "scn": boundary.scn,
        },
        extraction={
            "started_at": started_at.isoformat(),
            "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "row_count": write_result.row_count,
            "file_count": write_result.file_count,
        },
        primary_key=list(contract.primary_key),
        cursor=(
            {
                "column": contract.cursor_column,
                "lower": str(lower) if lower is not None else None,
                "upper": str(upper) if upper is not None else None,
            }
            if contract.cursor_column
            else None
        ),
        strategy=contract.strategy.value,
        schema_hash=inferred.schema_hash,
        files=write_result.files,
    )
    kind = "snapshot" if contract.strategy is SyncStrategy.full_replace else "increment"
    with metrics.stage_timer(contract.destination_name, "publish"):
        load_dir = lake_parquet.publish_load(
            staging_dir, inferred, boundary, manifest, kind=kind
        )
    state.record_table_run(
        run_id,
        boundary.load_id,
        contract,
        status="published_to_lake",
        rows_extracted=write_result.row_count,
        rows_written_to_lake=write_result.row_count,
    )

    with metrics.stage_timer(contract.destination_name, "warehouse_load"):
        rows_loaded = load_published_parquet(
            contract, load_dir, manifest, settings=settings
        )

    with metrics.stage_timer(contract.destination_name, "reconcile"):
        checks = reconciliation.reconcile_incremental(
            contract,
            run_id,
            rows_extracted=write_result.row_count,
            rows_written_to_lake=write_result.row_count,
            load_id=boundary.load_id,
            load_dir=load_dir,
        )
    if not all(c["passed"] for c in checks):
        state.record_table_run(
            run_id,
            boundary.load_id,
            contract,
            status="failed",
            error="incremental reconciliation failed",
            completed=True,
        )
        raise RuntimeError(
            f"Incremental reconciliation failed for {contract.qualified_name}"
        )

    new_cursor = reconciliation.max_cursor_value(contract) or (
        str(upper) if upper is not None else None
    )
    state.commit_watermark(
        contract,
        cursor_value=new_cursor,
        source_scn=boundary.scn,
        load_id=boundary.load_id,
    )
    state.record_table_run(
        run_id,
        boundary.load_id,
        contract,
        status="succeeded",
        rows_loaded_to_postgres=rows_loaded,
        completed=True,
    )
    return {
        "table": contract.qualified_name,
        "rows": write_result.row_count,
        "bytes": write_result.total_bytes,
        "load_id": boundary.load_id,
        "window": [str(lower), str(upper)],
    }


def _max_source_cursor(connection: Any, contract: TableContract) -> int:
    from app.dataplatform.oracle.metadata import validate_identifier

    schema = validate_identifier(contract.source_schema)
    table = validate_identifier(contract.source_table)
    column = validate_identifier(contract.cursor_column or "")
    cursor = connection.cursor()
    try:
        cursor.execute(f"SELECT max({column}) FROM {schema}.{table}")  # noqa: S608
        value = cursor.fetchone()[0]
        return int(value) if value is not None else 0
    finally:
        cursor.close()


def run_incremental(
    cadences: list[str],
    *,
    registry: Registry | None = None,
    tables: list[str] | None = None,
) -> dict[str, Any]:
    """Sync every enabled table due at the given cadence(s)."""
    registry = registry or load_registry()
    run_id = state.new_run_id()
    state.start_run(run_id, "incremental", {"cadences": cadences})
    stats = metrics.PipelineRunStats("incremental")
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    selected = {t.upper() for t in tables} if tables else None
    due = [
        c
        for c in registry.enabled()
        if c.cadence.value in cadences
        and (selected is None or c.qualified_name.upper() in selected)
    ]
    for contract in due:
        try:
            result = sync_table(contract, run_id)
            results.append(result)
            stats.record_table(
                contract.destination_name,
                rows=int(result.get("rows", 0)),
                size_bytes=int(result.get("bytes", 0)),
            )
        except Exception as exc:
            logger.exception("incremental sync failed for %s", contract.qualified_name)
            stats.record_table(contract.destination_name, succeeded=False)
            failures.append({"table": contract.qualified_name, "error": str(exc)})

    if results:
        refresh_catalog(registry)
    kpis = stats.finish()
    state.finish_run(
        run_id,
        "succeeded" if not failures else ("partial" if results else "failed"),
        {"synced": len(results), "failures": failures, "metrics": kpis},
    )
    return {
        "run_id": run_id,
        "synced": results,
        "failures": failures,
        "metrics": kpis,
    }
