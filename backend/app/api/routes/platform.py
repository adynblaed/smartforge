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

import json
import logging
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import (
    CurrentUser,
    InternalUser,
    get_current_active_superuser,
)
from app.dataplatform.config import get_platform_settings
from app.dataplatform.pipeline import plans as seed_plans
from app.dataplatform.pipeline import state as pipeline_state
from app.dataplatform.pipeline.freshness import table_freshness
from app.dataplatform.registry import load_registry
from app.dataplatform.warehouse.postgres import api_engine
from app.services.common import write_audit

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


# ---------------------------------------------------------------------------
# Targeted per-table sync (Omega catalogue action)
# ---------------------------------------------------------------------------


@router.get("/sync/estimate")
def sync_estimate(table: str, _: InternalUser) -> dict[str, Any]:
    """Pre-sync estimate for one contracted table, derived from the run
    history in the control schema (no source access — API-001): current
    record count from the latest loaded manifest, expected new records and
    duration from recent completed runs of the same table."""
    registry = load_registry()
    contract = registry.contracts.get(table.upper())
    if contract is None:
        raise HTTPException(status_code=404, detail="Unknown contracted table")
    try:
        with api_engine().connect() as connection:
            _arm_read_guards(connection)
            current_rows = connection.execute(
                sa.text(
                    """
                    SELECT row_count FROM control.replication_manifests
                     WHERE source_schema = :s AND source_table = :t
                       AND status = 'loaded'
                     ORDER BY published_at DESC LIMIT 1
                    """
                ),
                {"s": contract.source_schema, "t": contract.source_table},
            ).scalar()
            history = (
                connection.execute(
                    sa.text(
                        """
                        SELECT rows_loaded_to_postgres,
                               EXTRACT(EPOCH FROM (completed_at - started_at))
                          FROM control.replication_table_runs
                         WHERE source_schema = :s AND source_table = :t
                           AND status = 'succeeded' AND completed_at IS NOT NULL
                         ORDER BY started_at DESC LIMIT 5
                        """
                    ),
                    {"s": contract.source_schema, "t": contract.source_table},
                )
                .fetchall()
            )
    except Exception as exc:
        raise _warehouse_unavailable(exc) from None
    rows_history = [int(r[0] or 0) for r in history]
    secs_history = [float(r[1] or 0) for r in history]
    estimated_new = int(sum(rows_history) / len(rows_history)) if rows_history else 0
    # Never promise zero seconds: connect + publish + merge has a floor.
    estimated_seconds = max(
        5, int(sum(secs_history) / len(secs_history)) if secs_history else 60
    )
    return {
        "table": contract.qualified_name,
        "current_rows": int(current_rows or 0),
        "estimated_new_rows": estimated_new,
        "estimated_seconds": estimated_seconds,
        "basis": f"{len(rows_history)} recent completed runs",
    }


class TableSyncRequest(BaseModel):
    table: str


# In-process FIFO for user-triggered table syncs: rapid clicks enqueue
# instead of racing the single-flight lock (no more 409s from the UI).
# ONE daemon worker per process drains its queue sequentially; the
# cross-process advisory lock (INC-013) still arbitrates against the
# dispatcher, the CLI and the other uvicorn workers — the worker waits
# politely for it instead of failing. Each table gets up to
# _SYNC_MAX_ATTEMPTS tries with a self-heal + backoff between them; a
# table that exhausts its attempts fails SAFELY (watermark untouched,
# INC-004) and surfaces as status="failed" so the UI can offer a retry.
#
# Dedupe and status live in the _SyncCoordinator below — shared via Redis
# so the multi-worker API serves one truth (a poll must see the sync a
# DIFFERENT worker is running), degrading to per-process memory when
# Redis is unreachable (sandboxes, offline tests).
_sync_queue: queue.Queue[str] = queue.Queue()
_sync_state_lock = threading.Lock()
_sync_worker_started = False
_SYNC_LOCK_WAIT_SECONDS = 600
_SYNC_MAX_ATTEMPTS = 3
# Backoff before retry N+1 (after attempts 1 and 2).
_SYNC_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (5.0, 20.0)
# An in-flight claim older than this is treated as abandoned (a worker
# died mid-run) — the table becomes triggerable again.
_SYNC_INFLIGHT_TTL_SECONDS = 900.0


class _SyncCoordinator:
    """Cross-worker sync coordination state: per-table status entries
    (queued → running → succeeded | failed) shared through one Redis hash
    so every uvicorn worker answers /sync/status identically, with a
    per-process memory fallback when Redis is down. This is COORDINATION
    state, not a result cache — the no-server-side-result-cache policy
    (API-013) is untouched, and the control tables remain the durable
    record. Redis failures degrade silently (30 s retry window): the sync
    itself must never depend on Redis being up."""

    _STATUS_KEY = "smartforge:sync:status"
    _RETRY_SECONDS = 30.0

    def __init__(self) -> None:
        self._memory: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._client: Any = None
        self._degraded_until = 0.0

    def _redis(self) -> Any:
        if time.monotonic() < self._degraded_until:
            return None
        if self._client is None:
            try:
                import redis as redis_sync

                from app.core.config import settings

                self._client = redis_sync.Redis.from_url(
                    settings.REDIS_URL,
                    socket_connect_timeout=0.5,
                    socket_timeout=1.0,
                    decode_responses=True,
                )
            except Exception:
                self._client = None
                self._degrade()
        return self._client

    def _degrade(self) -> None:
        self._degraded_until = time.monotonic() + self._RETRY_SECONDS

    def _read_all(self) -> dict[str, dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        client = self._redis()
        if client is not None:
            try:
                for table, raw in client.hgetall(self._STATUS_KEY).items():
                    try:
                        merged[table] = json.loads(raw)
                    except (TypeError, ValueError):
                        continue
            except Exception:
                self._degrade()
        # The local view wins when strictly newer (covers the degraded
        # window where our own writes never reached Redis).
        with self._lock:
            for table, entry in self._memory.items():
                current = merged.get(table)
                if current is None or float(entry.get("epoch") or 0) >= float(
                    current.get("epoch") or 0
                ):
                    merged[table] = entry
        return merged

    def set_status(
        self,
        qualified: str,
        status: str,
        attempts: int,
        error: str | None = None,
    ) -> None:
        entry = {
            "status": status,
            "attempts": attempts,
            "error": error,
            "epoch": time.time(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._memory[qualified] = entry
        client = self._redis()
        if client is None:
            return
        try:
            client.hset(self._STATUS_KEY, qualified, json.dumps(entry))
        except Exception:
            self._degrade()

    @staticmethod
    def _entry_in_flight(entry: dict[str, Any] | None) -> bool:
        if not entry or entry.get("status") not in ("queued", "running"):
            return False
        age = time.time() - float(entry.get("epoch") or 0)
        return age < _SYNC_INFLIGHT_TTL_SECONDS

    def in_flight(self, qualified: str) -> bool:
        return self._entry_in_flight(self._read_all().get(qualified))

    def in_flight_count(self) -> int:
        return sum(
            1
            for entry in self._read_all().values()
            if self._entry_in_flight(entry)
        )

    def statuses(self) -> list[dict[str, Any]]:
        return [
            {
                "table": table,
                "status": entry.get("status"),
                "attempts": int(entry.get("attempts") or 0),
                "error": entry.get("error"),
                "updated_at": entry.get("updated_at"),
            }
            for table, entry in self._read_all().items()
        ]

    def reset(self) -> None:
        """Test hook: forget everything (memory + the shared hash)."""
        with self._lock:
            self._memory.clear()
        client = self._redis()
        if client is not None:
            try:
                client.delete(self._STATUS_KEY)
            except Exception:
                self._degrade()


_sync_coordinator = _SyncCoordinator()


def _set_sync_status(
    qualified: str, status: str, attempts: int, error: str | None = None
) -> None:
    _sync_coordinator.set_status(qualified, status, attempts, error)


def _audit_sync_trigger(actor_email: str, qualified: str) -> None:
    """Best-effort per-user audit of the trigger (app DB); an unreachable
    app DB must never block a platform sync."""
    try:
        from sqlmodel import Session, select

        from app.core.db import engine
        from app.models import User

        with Session(engine) as session:
            actor = session.exec(
                select(User).where(User.email == actor_email)
            ).first()
            write_audit(
                session,
                actor=actor,
                action="platform_table_sync_triggered",
                entity_type="omega_table",
                detail=f"{qualified} (by {actor_email})",
            )
    except Exception:  # pragma: no cover - audit is best-effort here
        logger.warning("sync trigger audit failed for %s", qualified)


def _audit_sync_failure(qualified: str, summary: str) -> None:
    """Best-effort audit of a terminal sync failure — the Logs warehouse/
    lake consoles weave these in so a failed operator sync is visible in
    the same streams as its trigger."""
    try:
        from sqlmodel import Session

        from app.core.db import engine

        with Session(engine) as session:
            write_audit(
                session,
                actor=None,
                action="platform_table_sync_failed",
                entity_type="omega_table",
                detail=f"{qualified} {summary}",
            )
    except Exception:  # pragma: no cover - audit is best-effort here
        logger.warning("sync failure audit failed for %s", qualified)


def _run_table_sync(qualified: str) -> None:
    """One targeted pipeline run. Dev sandboxes exercise the real pipeline
    over the sample source (self-locking); elsewhere a genuine windowed
    incremental under the advisory lock."""
    if get_platform_settings().PLATFORM_ENV == "development":
        from app.dataplatform.pipeline.sample_seed import run_sample_seed

        run_sample_seed(tables=[qualified])
    else:
        from app.dataplatform.pipeline.incremental import run_incremental

        with pipeline_state.pipeline_lock():
            run_incremental(["hourly", "daily", "manual"], tables=[qualified])


def _self_heal_sync(qualified: str, attempt: int) -> None:
    """Between-retry recovery: dispose and forget the cached warehouse
    engines so a poisoned connection pool can't doom every subsequent
    attempt (fresh connections on retry). Healing is best-effort — it must
    never raise and never touches data (the failed attempt already left
    the watermark and published loads untouched)."""
    try:
        from app.dataplatform.warehouse import postgres as warehouse_pg

        for cached_engine in (
            warehouse_pg.loader_engine,
            warehouse_pg.api_engine,
        ):
            try:
                cached_engine().dispose()
            except Exception:
                pass
            cached_engine.cache_clear()
    except Exception:  # pragma: no cover - healing is best-effort
        pass
    logger.warning(
        "table sync self-heal after attempt %d for %s "
        "(warehouse engine pools recycled)",
        attempt,
        qualified,
    )


def _attempt_table_sync(qualified: str) -> None:
    """One attempt, waiting politely for the cross-process pipeline lock;
    raises PipelineBusyError if the lock never frees within the budget so
    the attempt counts as a failure (and gets its retries)."""
    deadline = time.monotonic() + _SYNC_LOCK_WAIT_SECONDS
    while True:
        try:
            _run_table_sync(qualified)
            return
        except pipeline_state.PipelineBusyError:
            if time.monotonic() > deadline:
                raise
            time.sleep(3)


def _sync_worker() -> None:
    while True:
        qualified = _sync_queue.get()
        try:
            failure: Exception | None = None
            attempts_used = 0
            for attempt in range(1, _SYNC_MAX_ATTEMPTS + 1):
                attempts_used = attempt
                _set_sync_status(qualified, "running", attempt)
                try:
                    _attempt_table_sync(qualified)
                    failure = None
                    break
                except Exception as exc:
                    failure = exc
                    logger.exception(
                        "table sync attempt %d/%d failed for %s",
                        attempt,
                        _SYNC_MAX_ATTEMPTS,
                        qualified,
                    )
                    if attempt < _SYNC_MAX_ATTEMPTS:
                        _self_heal_sync(qualified, attempt)
                        time.sleep(
                            _SYNC_RETRY_BACKOFF_SECONDS[
                                min(
                                    attempt - 1,
                                    len(_SYNC_RETRY_BACKOFF_SECONDS) - 1,
                                )
                            ]
                        )
            if failure is None:
                _set_sync_status(qualified, "succeeded", attempts_used)
            else:
                # Expose only the exception CLASS — messages can carry
                # DSNs, paths or SQL (API-009 safe-error discipline).
                error_kind = type(failure).__name__
                summary = (
                    f"failed after {_SYNC_MAX_ATTEMPTS} attempts"
                    f" ({error_kind})"
                )
                _set_sync_status(
                    qualified, "failed", attempts_used, error_kind
                )
                _audit_sync_failure(qualified, summary)
        except Exception:  # pragma: no cover - worker must never die
            logger.exception("table sync worker crashed for %s", qualified)
            _set_sync_status(
                qualified, "failed", _SYNC_MAX_ATTEMPTS, "WorkerError"
            )
        finally:
            _sync_queue.task_done()


@router.get("/sync/status")
def table_sync_status(_: InternalUser) -> dict[str, Any]:
    """Live per-table status of user-triggered syncs (queued → running →
    succeeded | failed with attempt count). Shared across the multi-worker
    API through the sync coordinator (Redis-backed, memory fallback) —
    whichever worker answers, the UI sees the same truth; the control
    tables remain the durable record. Polled by the UI to stop spinners
    and surface 'Sync Failed' with a retry affordance."""
    statuses = _sync_coordinator.statuses()
    statuses.sort(key=lambda s: str(s.get("updated_at") or ""), reverse=True)
    return {"data": statuses, "count": len(statuses)}


@router.post(
    "/sync/table",
    dependencies=[Depends(get_current_active_superuser)],
)
def trigger_table_sync(
    body: TableSyncRequest,
    current_user: CurrentUser,
) -> dict[str, Any]:
    """User-triggered targeted sync of ONE contracted table (INC-012 ad hoc
    mode). Triggers ENQUEUE — rapid or overlapping requests serialize
    through one worker instead of surfacing lock conflicts; an already-
    queued table dedupes. The trigger is audited per user account (AuditLog
    → the Logs events/audit streams), and the pipeline records the run in
    the control tables — so the Omega catalogue, EDA views and service
    logs all read the same event."""
    registry = load_registry()
    contract = registry.contracts.get(body.table.upper())
    if contract is None:
        raise HTTPException(status_code=404, detail="Unknown contracted table")
    qualified = contract.qualified_name

    global _sync_worker_started
    with _sync_state_lock:
        # Cross-worker dedupe: an in-flight claim (queued/running, not yet
        # expired) on ANY uvicorn worker reads as already_queued here. The
        # check-then-claim window is not atomic across processes — a race
        # merely double-enqueues, and the advisory lock (INC-013) plus the
        # idempotent merge make the duplicate run harmless.
        already_queued = _sync_coordinator.in_flight(qualified)
        if not already_queued:
            _sync_coordinator.set_status(qualified, "queued", 0)
            _sync_queue.put(qualified)
            if not _sync_worker_started:
                threading.Thread(
                    target=_sync_worker, daemon=True, name="table-sync-worker"
                ).start()
                _sync_worker_started = True
        queue_depth = _sync_coordinator.in_flight_count()

    _audit_sync_trigger(current_user.email, qualified)
    return {
        "status": "already_queued" if already_queued else "queued",
        "table": qualified,
        "queue_depth": queue_depth,
        "triggered_by": current_user.email,
        "monitor": "/api/v1/platform/replication/runs",
    }
