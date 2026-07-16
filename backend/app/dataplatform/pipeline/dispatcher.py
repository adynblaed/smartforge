"""Cadence dispatcher with single-flight locking (Specs §21, Migration §9).

Phase 0/1 orchestration: an external scheduler (cron / Task Scheduler /
compose worker loop) invokes `dispatch()` hourly. The dispatcher decides
which cadences are due, takes a Postgres advisory lock so overlapping runs
can never double-write (INC-013), runs incremental sync, delete
reconciliation when due, then dbt build + tests. Every non-skipped tick
ends with lake maintenance — snapshot retention pruning and abandoned
staging sweep (LAKE-011) — whose failures never fail the tick.
"""

from __future__ import annotations

import datetime as dt
import logging
import subprocess
import time
from pathlib import Path
from typing import Any

from app.dataplatform import metrics
from app.dataplatform.config import get_platform_settings
from app.dataplatform.lake import parquet as lake_parquet
from app.dataplatform.pipeline import state
from app.dataplatform.pipeline.incremental import run_incremental
from app.dataplatform.pipeline.reconcile_deletes import run_delete_reconciliation
from app.dataplatform.registry import Registry, load_registry
from app.dataplatform.warehouse.postgres import loader_engine

logger = logging.getLogger(__name__)


def due_cadences(now: dt.datetime | None = None) -> list[str]:
    """Hourly always; daily at 02:00 UTC; weekly Sundays at 03:00 UTC."""
    now = now or dt.datetime.now(dt.timezone.utc)
    cadences = ["hourly"]
    if now.hour == 2:
        cadences.append("daily")
    if now.weekday() == 6 and now.hour == 3:
        cadences.append("weekly")
    return cadences


def run_dbt(targets: list[str] | None = None) -> dict[str, Any]:
    """dbt build for both warehouse (postgres) and lake (duckdb) targets."""
    settings = get_platform_settings()
    results: dict[str, Any] = {}
    for target in targets or ["warehouse", "lake"]:
        with metrics.stage_timer("_pipeline_", f"dbt_{target}"):
            completed = subprocess.run(  # noqa: S603
                [
                    "dbt",
                    "build",
                    "--project-dir",
                    str(settings.dbt_project_dir),
                    "--profiles-dir",
                    str(settings.dbt_project_dir),
                    "--target",
                    target,
                ],
                capture_output=True,
                text=True,
                timeout=3600,
            )
        results[target] = {
            "returncode": completed.returncode,
            "tail": completed.stdout[-4000:],
        }
        if completed.returncode != 0:
            # Bounded stdout tail for triage. dbt stdout may echo model SQL
            # (repo-reviewed code, never data values); dbt masks connection
            # credentials, so no secret can appear here (OBS-006).
            logger.error(
                "dbt build failed for target=%s:\n%s", target, completed.stdout[-4000:]
            )
            # Failed dbt tests block mart publication (DBT-008); raw load
            # is retained, marts stay stale until repaired (Specs §24.3).
            raise RuntimeError(f"dbt build failed for target {target}")
        logger.info("dbt build succeeded for target=%s", target)
    return results


def _newest_mtime(root: Path) -> float:
    """Most recent modification time anywhere under a staging directory."""
    newest = root.stat().st_mtime
    for path in root.rglob("*"):
        newest = max(newest, path.stat().st_mtime)
    return newest


def lake_maintenance(registry: Registry | None = None) -> dict[str, Any]:
    """Post-dispatch lake housekeeping (LAKE-011).

    Prunes every enabled table's published snapshot partitions down to
    LAKE_RETAINED_SNAPSHOTS and quarantines abandoned staging directories
    untouched for longer than PIPELINE_LOCK_TTL_SECONDS (no live run can
    still own them once the lock TTL has passed). Per-item failures are
    logged and swallowed: maintenance never fails a successful tick.
    """
    settings = get_platform_settings()
    registry = registry or load_registry()
    snapshots_pruned = 0
    quarantined: list[str] = []
    warnings = 0

    for contract in registry.enabled():
        table_dir = contract.lake_table_dir(settings.lake_published_dir)
        if not table_dir.exists():
            continue
        try:
            snapshots_pruned += len(
                lake_parquet.prune_snapshots(
                    table_dir, settings.LAKE_RETAINED_SNAPSHOTS
                )
            )
        except Exception:
            warnings += 1
            logger.warning(
                "snapshot pruning failed for %s; maintenance continues",
                contract.qualified_name,
                exc_info=True,
            )

    staging_root = settings.lake_staging_dir
    cutoff = time.time() - settings.PIPELINE_LOCK_TTL_SECONDS
    if staging_root.exists():
        for load_dir in sorted(staging_root.iterdir()):
            if not load_dir.is_dir():
                continue
            try:
                if _newest_mtime(load_dir) >= cutoff:
                    continue  # fresh enough — a live run may still own it
                for table_dir in sorted(p for p in load_dir.iterdir() if p.is_dir()):
                    target = lake_parquet.quarantine_load(
                        table_dir,
                        "abandoned staging directory swept by lake maintenance"
                        " (idle longer than PIPELINE_LOCK_TTL_SECONDS="
                        f"{settings.PIPELINE_LOCK_TTL_SECONDS}s, LAKE-011)",
                        settings=settings,
                    )
                    quarantined.append(str(target))
                if not any(load_dir.iterdir()):
                    load_dir.rmdir()
            except Exception:
                warnings += 1
                logger.warning(
                    "staging sweep failed for %s; maintenance continues",
                    load_dir,
                    exc_info=True,
                )

    logger.info(
        "lake maintenance: pruned %d snapshot partition(s), quarantined %d "
        "stale staging dir(s), %d warning(s)",
        snapshots_pruned,
        len(quarantined),
        warnings,
    )
    return {
        "snapshots_pruned": snapshots_pruned,
        "staging_quarantined": quarantined,
        "warnings": warnings,
    }


def dispatch(
    *,
    cadences: list[str] | None = None,
    with_dbt: bool = True,
) -> dict[str, Any]:
    """One dispatcher tick. Safe to invoke repeatedly (single-flight)."""
    registry = load_registry()
    cadences = cadences or due_cadences()
    engine = loader_engine()

    with engine.connect() as lock_connection:
        if not state.acquire_pipeline_lock(lock_connection):
            logger.warning("another pipeline run holds the lock; skipping tick")
            return {"status": "skipped", "reason": "pipeline lock held"}

        summary: dict[str, Any] = {"cadences": cadences}
        sync_result = run_incremental(cadences, registry=registry)
        summary["sync"] = sync_result

        if "weekly" in cadences or "daily" in cadences:
            summary["delete_reconciliation"] = run_delete_reconciliation(
                registry=registry, cadences=cadences
            )

        if with_dbt and sync_result["synced"]:
            try:
                summary["dbt"] = run_dbt()
            except (RuntimeError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
                summary["dbt"] = {"error": str(exc)}
                summary["status"] = "partial"
                return summary

        # Post-dbt housekeeping under the same lock; never fails the tick
        # and never runs on a lock-skipped tick (LAKE-011).
        try:
            summary["lake_maintenance"] = lake_maintenance(registry)
        except Exception as exc:
            logger.warning("lake maintenance failed; dispatch unaffected: %s", exc)
            summary["lake_maintenance"] = {"error": str(exc)}

        summary["status"] = "succeeded" if not sync_result["failures"] else "partial"
        # The advisory lock releases when this connection closes.
        return summary
