"""Sandbox seed: the real pipeline fed by the deterministic sample source.

Development-only (`PLATFORM_ENV=development`, refused otherwise): stands in
for the omega Oracle so the full seed lifecycle — staged Parquet, row-count
validation, atomic publish + manifest, dlt merge into the warehouse,
watermark-last commit, DuckDB catalog refresh, dbt build — runs end to end
against the sandbox stores. Everything downstream (Data Platform page,
Work Orders explorer, MRP page) then serves genuinely seeded data.

What it deliberately does NOT do: contact Oracle, bypass contracts, or
fabricate reconciliation evidence — source-side checks need a source, so
the recorded checks here are lake/warehouse only, labeled as such.

Prerequisite: `cli bootstrap` (control tables must exist).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import pyarrow as pa

from app.dataplatform import metrics
from app.dataplatform.config import PlatformSettings, get_platform_settings
from app.dataplatform.lake import parquet as lake_parquet
from app.dataplatform.lake.duckdb_catalog import refresh_catalog
from app.dataplatform.lake.manifest import LoadManifest
from app.dataplatform.oracle.extractor import (
    _coerce,
    build_arrow_schema,
    resolve_uid_key_indexes,
    surrogate_uid_arrays,
)
from app.dataplatform.oracle.metadata import InferredTable
from app.dataplatform.oracle.snapshot import SourceBoundary
from app.dataplatform.pipeline import reconciliation, state
from app.dataplatform.registry import Registry, load_registry
from app.dataplatform.sample_source import build_sample_dataset
from app.dataplatform.warehouse.loader import (
    load_published_parquet,
    warehouse_row_count,
)

logger = logging.getLogger(__name__)


class SampleSeedRefusedError(RuntimeError):
    """Raised outside the development environment — the sandbox seed must
    never be mistaken for (or run against) a production store."""


def sample_batches(
    inferred: InferredTable, boundary: SourceBoundary, rows: list[dict[str, Any]]
) -> list[pa.RecordBatch]:
    """One Arrow batch with the exact extractor layout: business columns,
    surrogate UUIDs (DCT-011), then ingestion metadata (DCT-012)."""
    contract = inferred.contract
    schema = build_arrow_schema(inferred)
    columns = [c.name for c in inferred.columns]
    uid_indexes = resolve_uid_key_indexes(contract, columns)
    extracted_at = dt.datetime.now(dt.timezone.utc)

    n = len(rows)
    column_values: list[list[Any]] = [
        [_coerce(row.get(name), schema.field(i).type) for row in rows]
        for i, name in enumerate(columns)
    ]
    arrays = [
        pa.array(column_values[i], type=schema.field(i).type)
        for i in range(len(columns))
    ]
    arrays += surrogate_uid_arrays(contract, uid_indexes, column_values, n)
    arrays += [
        pa.array([contract.source_system] * n, type=pa.string()),
        pa.array([contract.source_schema] * n, type=pa.string()),
        pa.array([contract.source_table] * n, type=pa.string()),
        pa.array([boundary.scn] * n, type=pa.int64()),
        pa.array([boundary.load_id] * n, type=pa.string()),
        pa.array([extracted_at] * n, type=pa.timestamp("us", tz="UTC")),
        pa.array([False] * n, type=pa.bool_()),
    ]
    return [pa.RecordBatch.from_arrays(arrays, schema=schema)]


def _seed_sample_table(
    inferred: InferredTable,
    rows: list[dict[str, Any]],
    boundary: SourceBoundary,
    run_id: str,
) -> dict[str, Any]:
    """Mirror of full_seed.seed_table with the sample source standing in for
    Oracle: same publish -> load -> validate -> watermark-last ordering."""
    contract = inferred.contract
    settings = get_platform_settings()
    started_at = dt.datetime.now(dt.timezone.utc)
    state.record_table_run(
        run_id, boundary.load_id, contract, status="extracting", source_scn=boundary.scn
    )

    schema = build_arrow_schema(inferred)
    batches = sample_batches(inferred, boundary, rows)
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
            "database": "SAMPLE",  # never attributable to a real omega DB
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
            {"column": contract.cursor_column, "lower": None, "upper": None}
            if contract.cursor_column
            else None
        ),
        strategy=contract.strategy.value,
        schema_hash=inferred.schema_hash,
        files=write_result.files,
    )
    with metrics.stage_timer(contract.destination_name, "publish"):
        load_dir = lake_parquet.publish_load(
            staging_dir, inferred, boundary, manifest, kind="snapshot"
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
    state.record_schema_version(
        contract,
        inferred.schema_hash,
        [c.model_dump(exclude={"contract"}) for c in inferred.columns],
    )

    # Lake vs warehouse validation (no Oracle, so no source-side checks).
    with metrics.stage_timer(contract.destination_name, "reconcile"):
        warehouse_rows = warehouse_row_count(contract.destination_name)
    if warehouse_rows is not None and warehouse_rows < write_result.row_count:
        state.record_table_run(
            run_id,
            boundary.load_id,
            contract,
            status="failed",
            error="sample seed count validation failed",
            completed=True,
        )
        raise RuntimeError(
            f"Sample seed validation failed for {contract.qualified_name}: "
            f"warehouse has {warehouse_rows} rows < published {write_result.row_count}"
        )

    # Watermark commits ONLY now — same ordering contract as a real seed
    # (INC-005), so the sandbox rehearses the invariant, not a shortcut.
    cursor_value = reconciliation.max_cursor_value(contract)
    state.commit_watermark(
        contract,
        cursor_value=cursor_value,
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
    }


def run_sample_seed(
    *,
    registry: Registry | None = None,
    tables: list[str] | None = None,
    with_dbt: bool = True,
) -> dict[str, Any]:
    """Seed every contracted table from the sample source (dev only)."""
    settings = get_platform_settings()
    if settings.PLATFORM_ENV != "development":
        raise SampleSeedRefusedError(
            "sample-seed is a development-sandbox tool and is refused when "
            f"PLATFORM_ENV={settings.PLATFORM_ENV!r} — production data comes "
            "only from the gated seed workflow (QUICKSTART.md)."
        )
    registry = registry or load_registry()
    # Same single-flight guard as every other writer entry point (INC-013):
    # even the sandbox seed must not overlap a dispatcher tick.
    with state.pipeline_lock():
        return _run_sample_seed_locked(registry, settings, tables, with_dbt)


def _run_sample_seed_locked(
    registry: Registry,
    settings: PlatformSettings,
    tables: list[str] | None,
    with_dbt: bool,
) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    # Millisecond pseudo-SCN: monotonic so replays respect load ordering
    # (INC-006) AND distinct across back-to-back reruns — repeating the
    # command is always safe (merge dedupes, full_replace replaces).
    boundary = SourceBoundary(
        scn=int(now.timestamp() * 1000),
        source_timestamp_utc=now,
        captured_at_utc=now,
    )
    dataset = build_sample_dataset(registry)
    selected = {t.upper() for t in tables} if tables else None

    run_id = state.new_run_id()
    state.start_run(run_id, "sample_seed", {"source": "sample", "scn": boundary.scn})
    stats = metrics.PipelineRunStats("sample_seed", source="sample")
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    kpis: dict[str, Any] = {}
    try:
        for qualified, (inferred, rows) in dataset.items():
            contract = inferred.contract
            if not contract.enabled:
                continue
            if selected is not None and qualified.upper() not in selected:
                continue
            try:
                result = _seed_sample_table(inferred, rows, boundary, run_id)
                results.append(result)
                stats.record_table(
                    contract.destination_name,
                    rows=int(result.get("rows", 0)),
                    size_bytes=int(result.get("bytes", 0)),
                )
            except Exception as exc:
                logger.exception("sample seed failed for %s", qualified)
                stats.record_table(contract.destination_name, succeeded=False)
                failures.append({"table": qualified, "error": str(exc)})
                # Leave no half-staged directory behind: repeatability
                # means a failed rerun never trips over its own debris.
                staged = (
                    settings.lake_staging_dir
                    / f"load_id={boundary.load_id}"
                    / contract.destination_name
                )
                if staged.exists():
                    lake_parquet.quarantine_load(staged, f"sample seed failed: {exc}")
        refresh_catalog(registry)
        # Repeat runs must not grow the lake without bound: apply the same
        # retention the dispatcher applies (LAKE-011).
        for contract in registry.enabled():
            table_dir = contract.lake_table_dir(settings.lake_published_dir)
            if table_dir.exists():
                lake_parquet.prune_snapshots(
                    table_dir, settings.LAKE_RETAINED_SNAPSHOTS
                )
        dbt_result: dict[str, Any] | None = None
        if with_dbt and not failures:
            from app.dataplatform.pipeline.dispatcher import run_dbt

            dbt_result = run_dbt(None)
    finally:
        kpis = stats.finish()
        state.finish_run(
            run_id,
            "succeeded" if not failures else "failed",
            {"tables_seeded": len(results), "failures": failures, "metrics": kpis},
        )
    return {
        "run_id": run_id,
        "status": "succeeded" if not failures else "failed",
        "seeded": results,
        "failures": failures,
        "dbt": dbt_result,
        "metrics": kpis,
    }
