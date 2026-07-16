"""Initial consistent seed (Specs §8, Checklist §8 SEED-*).

Every table is extracted AS OF one captured SCN, written to unpublished
staging Parquet, validated, atomically published with a manifest, then
loaded into PostgreSQL and registered in DuckDB — both destinations
demonstrably represent the same source snapshot (SEED-009).

Seeding NEVER runs without an operator-confirmed SeedPlan
(SEED_REQUIRE_CONFIRMATION): see app.dataplatform.pipeline.plans.
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
from app.dataplatform.oracle.connection import oracle_connection, verify_read_only
from app.dataplatform.oracle.extractor import build_arrow_schema, extract_batches
from app.dataplatform.oracle.metadata import InferredTable, SeedPlan
from app.dataplatform.oracle.snapshot import capture_boundary, supports_flashback
from app.dataplatform.pipeline import reconciliation, state
from app.dataplatform.registry import Registry, load_registry
from app.dataplatform.warehouse.loader import load_published_parquet

logger = logging.getLogger(__name__)


def seed_table(
    connection: Any,
    inferred: InferredTable,
    boundary: Any,
    run_id: str,
    *,
    use_flashback: bool,
) -> dict[str, Any]:
    contract = inferred.contract
    settings = get_platform_settings()
    started_at = dt.datetime.now(dt.timezone.utc)
    state.record_table_run(
        run_id, boundary.load_id, contract, status="extracting", source_scn=boundary.scn
    )

    schema = build_arrow_schema(inferred)
    batches = extract_batches(
        connection, inferred, boundary, use_flashback=use_flashback
    )
    # write_staged_load consumes the extraction stream, so this stage times
    # Oracle read + Parquet staging together (the true source-to-lake cost).
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

    with metrics.stage_timer(contract.destination_name, "reconcile"):
        checks = reconciliation.reconcile_seed(
            connection,
            contract,
            boundary,
            write_result.row_count,
            run_id,
            use_flashback=use_flashback,
            load_id=boundary.load_id,
            load_dir=load_dir,
        )
    all_passed = all(c["passed"] for c in checks)
    if not all_passed:
        state.record_table_run(
            run_id,
            boundary.load_id,
            contract,
            status="failed",
            error="seed reconciliation failed",
            completed=True,
        )
        raise RuntimeError(
            f"Seed reconciliation failed for {contract.qualified_name}: {checks}"
        )

    # Watermark commits ONLY now: extraction + lake + warehouse + checks done.
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
        "checks": checks,
    }


def run_full_seed(
    plan: SeedPlan,
    *,
    registry: Registry | None = None,
    tables: list[str] | None = None,
) -> dict[str, Any]:
    """Execute a confirmed seed plan end to end."""
    registry = registry or load_registry()
    run_id = state.new_run_id()
    state.start_run(run_id, "seed", {"plan_id": plan.plan_id})
    stats = metrics.PipelineRunStats("seed")
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    selected = {t.upper() for t in tables} if tables else None
    inferred_tables = [
        t
        for t in plan.tables
        if selected is None or t.contract.qualified_name.upper() in selected
    ]

    try:
        with oracle_connection() as connection:
            evidence = verify_read_only(connection)
            logger.info(
                "read-only verified for seed: %d session privileges",
                len(evidence["session_privileges"]),
            )
            boundary = capture_boundary(connection)
            use_flashback = (
                supports_flashback(
                    connection, inferred_tables[0].contract.qualified_name
                )
                if inferred_tables
                else False
            )
            if not use_flashback:
                logger.warning(
                    "flashback unavailable — seeding without AS OF SCN; the "
                    "snapshot boundary is approximate (SEED-001 Method C)."
                )
            for inferred in inferred_tables:
                try:
                    result = seed_table(
                        connection,
                        inferred,
                        boundary,
                        run_id,
                        use_flashback=use_flashback,
                    )
                    results.append(result)
                    stats.record_table(
                        inferred.contract.destination_name,
                        rows=int(result.get("rows", 0)),
                        size_bytes=int(result.get("bytes", 0)),
                    )
                except Exception as exc:
                    logger.exception(
                        "seed failed for %s", inferred.contract.qualified_name
                    )
                    stats.record_table(
                        inferred.contract.destination_name, succeeded=False
                    )
                    failures.append(
                        {"table": inferred.contract.qualified_name, "error": str(exc)}
                    )
        refresh_catalog(registry)
    finally:
        status = "succeeded" if not failures else "failed"
        kpis = stats.finish()
        state.finish_run(
            run_id,
            status,
            {"tables_seeded": len(results), "failures": failures, "metrics": kpis},
        )

    return {
        "run_id": run_id,
        "status": "succeeded" if not failures else "failed",
        "seeded": results,
        "failures": failures,
        "metrics": kpis,
    }
