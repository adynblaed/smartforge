"""Data-platform operations API (tag: data-platform).

Replication status, freshness, reconciliation evidence, discovery and the
confirm-before-seed flow. Read endpoints require internal staff; anything
that touches the omega source or mutates platform state requires a
superuser. Long steps (seed, sync) run as background work and are
observable through /platform/replication/runs.

Boundary statement (API-001 scope): the *data-serving* surface
(/warehouse, /lake, every app domain) never touches Oracle. The superuser
operations here — discovery, seed, sync — are the deliberate control-plane
exception: they reach the omega source (read-only, verified at connect)
and the lake/warehouse writers from the API process. Every such writer run
executes under the pipeline single-flight lock (INC-013), so an operator
trigger can never overlap a dispatcher tick or another operator.
"""

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import InternalUser, get_current_active_superuser
from app.dataplatform.config import get_platform_settings
from app.dataplatform.pipeline import plans as seed_plans
from app.dataplatform.pipeline import state as pipeline_state
from app.dataplatform.pipeline.freshness import table_freshness
from app.dataplatform.registry import load_registry
from app.dataplatform.warehouse.postgres import api_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/platform", tags=["data-platform"])


def _ensure_pipeline_idle() -> None:
    """Fail fast (409) when a pipeline run is already in flight.

    A momentary acquire-and-release probe: the background task re-acquires
    the lock for real, so the tiny race window between probe and execution
    is still closed by the hard guard in the task itself.
    """
    try:
        with pipeline_state.pipeline_lock():
            pass
    except pipeline_state.PipelineBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception as exc:
        raise _warehouse_unavailable(exc) from None


def _arm_read_guards(connection: Any) -> None:
    """READ ONLY first (transaction-mode ordering), then the statement
    timeout — the same bounded-read discipline as /warehouse (API-007/008),
    so no control-table scan can hang a request handler."""
    connection.execute(sa.text("SET TRANSACTION READ ONLY"))
    connection.execute(
        sa.text(
            f"SET statement_timeout = "
            f"{get_platform_settings().API_STATEMENT_TIMEOUT_MS}"
        )
    )


def _warehouse_unavailable(exc: Exception) -> HTTPException:
    logger.warning("warehouse unavailable: %s", exc)
    return HTTPException(
        status_code=503,
        detail=(
            "Analytics warehouse is not reachable or not bootstrapped. "
            "Run `python -m app.dataplatform.cli bootstrap` first."
        ),
    )


# ---------------------------------------------------------------------------
# Status / observability
# ---------------------------------------------------------------------------


@router.get("/health")
def platform_health(_: InternalUser) -> dict[str, Any]:
    settings = get_platform_settings()
    warehouse_ok = False
    try:
        with api_engine().connect() as connection:
            connection.execute(sa.text("SELECT 1"))
        warehouse_ok = True
    except Exception:  # pragma: no cover - connectivity probe
        pass
    return {
        "warehouse": "ok" if warehouse_ok else "unavailable",
        "duckdb_catalog": "ok" if settings.DUCKDB_PATH.exists() else "missing",
        "lake_root": str(settings.LAKE_ROOT),
        "lake_published": settings.lake_published_dir.exists(),
        "environment": settings.PLATFORM_ENV,
    }


@router.get("/replication/tables")
def replication_tables(_: InternalUser) -> dict[str, Any]:
    """Registry contracts joined with committed watermarks + freshness."""
    registry = load_registry()
    try:
        freshness = {f["table"]: f for f in table_freshness(registry)}
    except Exception as exc:
        raise _warehouse_unavailable(exc) from None
    tables = []
    for contract in registry.contracts.values():
        entry: dict[str, Any] = {
            "table": contract.qualified_name,
            "destination": contract.destination_name,
            "enabled": contract.enabled,
            "cadence": contract.cadence.value,
            "strategy": contract.strategy.value,
            "primary_key": contract.primary_key,
            "cursor_column": contract.cursor_column,
            "delete_strategy": contract.delete_strategy.value,
            "classification": contract.classification,
            "owner": contract.owner,
        }
        entry.update(
            {
                k: v
                for k, v in freshness.get(contract.qualified_name, {}).items()
                if k
                in (
                    "status",
                    "lag_minutes",
                    "last_load_id",
                    "last_published_at",
                    "source_scn",
                )
            }
        )
        tables.append(entry)
    return {"data": tables, "count": len(tables)}


@router.get("/replication/runs")
def replication_runs(_: InternalUser, limit: int = 20) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    try:
        with api_engine().connect() as connection:
            _arm_read_guards(connection)
            runs = (
                connection.execute(
                    sa.text(
                        """
                    SELECT run_id, kind, status, started_at, completed_at, detail
                      FROM control.replication_runs
                     ORDER BY started_at DESC LIMIT :limit
                    """
                    ),
                    {"limit": limit},
                )
                .mappings()
                .all()
            )
            table_runs = (
                connection.execute(
                    sa.text(
                        """
                    SELECT run_id, load_id, source_schema, source_table,
                           strategy, status, source_scn, cursor_lower,
                           cursor_upper, rows_extracted, rows_written_to_lake,
                           rows_loaded_to_postgres, rows_rejected, error,
                           started_at, completed_at
                      FROM control.replication_table_runs
                     ORDER BY started_at DESC LIMIT :limit
                    """
                    ),
                    {"limit": limit * 5},
                )
                .mappings()
                .all()
            )
    except Exception as exc:
        raise _warehouse_unavailable(exc) from None
    return {
        "runs": [dict(r) for r in runs],
        "table_runs": [dict(r) for r in table_runs],
    }


@router.get("/freshness")
def freshness(_: InternalUser) -> dict[str, Any]:
    try:
        report = table_freshness()
    except Exception as exc:
        raise _warehouse_unavailable(exc) from None
    worst = "fresh"
    for row in report:
        if row["status"] in ("stale", "never_loaded"):
            worst = "stale"
            break
        if row["status"] == "warning":
            worst = "warning"
    return {"overall": worst, "tables": report}


@router.get("/reconciliation")
def reconciliation_results(_: InternalUser, limit: int = 50) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    try:
        with api_engine().connect() as connection:
            _arm_read_guards(connection)
            rows = (
                connection.execute(
                    sa.text(
                        """
                    SELECT run_id, source_schema, source_table, check_name,
                           source_value, target_value, passed, checked_at
                      FROM audit.reconciliation_results
                     ORDER BY checked_at DESC LIMIT :limit
                    """
                    ),
                    {"limit": limit},
                )
                .mappings()
                .all()
            )
    except Exception as exc:
        raise _warehouse_unavailable(exc) from None
    return {"data": [dict(r) for r in rows], "count": len(rows)}


# ---------------------------------------------------------------------------
# Discovery + confirm-before-seed
# ---------------------------------------------------------------------------


class DiscoveryResponse(BaseModel):
    """Summary of a persisted discovery plan awaiting operator review; nothing
    is seeded until this plan's fingerprint is explicitly confirmed."""

    plan_id: str
    fingerprint: str
    seedable: bool
    blocking_issues: list[str]
    table_count: int


@router.post(
    "/discovery/run",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=DiscoveryResponse,
)
def run_discovery() -> DiscoveryResponse:
    """Connect to omega read-only, infer target schemas, persist a plan.

    Synchronous: metadata-only queries are cheap on the source.
    """
    try:
        plan = seed_plans.discover()
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception as exc:
        logger.exception("discovery failed")
        raise HTTPException(
            status_code=502,
            detail=f"Omega discovery failed: {type(exc).__name__}",
        ) from None
    return DiscoveryResponse(
        plan_id=plan.plan_id,
        fingerprint=plan.fingerprint(),
        seedable=plan.is_seedable,
        blocking_issues=plan.blocking_issues,
        table_count=len(plan.tables),
    )


@router.get("/seed/plan")
def get_seed_plan(_: InternalUser) -> dict[str, Any]:
    """The latest reviewable plan, with per-table inferred schemas."""
    try:
        plan = seed_plans.latest_plan()
    except Exception as exc:
        raise _warehouse_unavailable(exc) from None
    if plan is None:
        raise HTTPException(
            status_code=404,
            detail="No seed plan proposed yet. Run discovery first.",
        )
    return {
        "plan_id": plan.plan_id,
        "fingerprint": plan.fingerprint(),
        "created_at": plan.created_at,
        "status": seed_plans.plan_status(plan.plan_id),
        "oracle_host": plan.oracle_host,
        "oracle_service": plan.oracle_service,
        "seedable": plan.is_seedable,
        "blocking_issues": plan.blocking_issues,
        "confirmation_phrase": seed_plans.CONFIRMATION_PHRASE,
        "tables": [
            {
                "table": t.contract.qualified_name,
                "destination": t.contract.destination_name,
                "strategy": t.contract.strategy.value,
                "cadence": t.contract.cadence.value,
                "primary_key": t.contract.primary_key,
                "estimated_rows": t.estimated_rows,
                "estimated_mb": t.estimated_mb,
                "pk_verified": t.primary_key_verified,
                "cursor_verified": t.cursor_verified,
                "schema_hash": t.schema_hash,
                "warnings": t.warnings,
                "columns": [
                    {
                        "source": c.name,
                        "destination": c.destination_name,
                        "oracle_type": c.oracle_type,
                        "postgres_type": c.postgres_type,
                        "duckdb_type": c.duckdb_type,
                        "nullable": c.nullable,
                        "primary_key": c.is_primary_key,
                    }
                    for c in t.columns
                ],
            }
            for t in plan.tables
        ],
    }


class SeedConfirmRequest(BaseModel):
    """Operator confirmation for the confirm-before-seed gate: the fingerprint
    and phrase must match the reviewed plan exactly, or nothing runs."""

    plan_id: str
    fingerprint: str
    confirmation_phrase: str = Field(
        description="Must equal the confirmation phrase shown on the plan"
    )
    tables: list[str] | None = None


@router.post("/seed/confirm")
def confirm_and_seed(
    body: SeedConfirmRequest,
    background: BackgroundTasks,
    current_user: Any = Depends(get_current_active_superuser),
) -> dict[str, Any]:
    """Explicit human gate: validates phrase + fingerprint, then seeds.

    The seed itself runs in the background (it can take a long time);
    progress is visible in /platform/replication/runs.
    """
    try:
        plan = seed_plans.confirm_plan(
            body.plan_id,
            body.fingerprint,
            body.confirmation_phrase,
            confirmed_by=str(current_user.email),
        )
    except seed_plans.PlanNotConfirmedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception as exc:
        raise _warehouse_unavailable(exc) from None
    _ensure_pipeline_idle()

    def _execute() -> None:
        from app.dataplatform.pipeline.full_seed import run_full_seed

        try:
            # Hard single-flight guard (INC-013): an API-triggered seed can
            # never overlap a dispatcher tick or another operator run.
            with pipeline_state.pipeline_lock():
                result = run_full_seed(plan, tables=body.tables)
            seed_plans.mark_executed(plan.plan_id, result)
        except pipeline_state.PipelineBusyError:
            logger.error(
                "background seed for plan %s skipped: pipeline lock held; "
                "the confirmed plan remains executable — re-trigger once the "
                "running pipeline finishes",
                plan.plan_id,
            )
        except Exception:
            logger.exception("background seed execution failed")

    background.add_task(_execute)
    return {
        "status": "seeding_started",
        "plan_id": plan.plan_id,
        "tables": body.tables or [t.contract.qualified_name for t in plan.tables],
        "monitor": "/api/v1/platform/replication/runs",
    }


class SyncRequest(BaseModel):
    """Scope for an operator-triggered ad hoc sync (INC-012) — restricted to
    contracted cadences/tables, never arbitrary source objects."""

    cadences: list[str] = Field(default_factory=lambda: ["hourly"])
    tables: list[str] | None = None


@router.post("/sync/run")
def trigger_sync(
    body: SyncRequest,
    background: BackgroundTasks,
    _: Any = Depends(get_current_active_superuser),
) -> dict[str, Any]:
    """Operator-triggered ad hoc sync (INC-012 ad hoc mode)."""
    _ensure_pipeline_idle()

    def _execute() -> None:
        from app.dataplatform.pipeline.incremental import run_incremental

        try:
            # Hard single-flight guard (INC-013), same as the dispatcher.
            with pipeline_state.pipeline_lock():
                run_incremental(body.cadences, tables=body.tables)
        except pipeline_state.PipelineBusyError:
            logger.error(
                "background sync skipped: pipeline lock held; retry once the "
                "running pipeline finishes"
            )
        except Exception:
            logger.exception("background sync failed")

    background.add_task(_execute)
    return {"status": "sync_started", "monitor": "/api/v1/platform/replication/runs"}
