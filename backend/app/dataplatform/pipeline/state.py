"""Durable pipeline state in the warehouse control schema.

Watermark rules (Specs §16.3/§3.5, Checklist INC-005/DLT-001):
  * state lives in PostgreSQL, not local files — survives worker replacement;
  * a watermark advances ONLY after publication + load + validation succeed;
  * failed runs leave the committed watermark untouched.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa

from app.dataplatform.registry import TableContract
from app.dataplatform.warehouse.postgres import loader_engine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Watermark:
    """Committed replication position for one table (INC-005).

    Reflects only fully validated publications: it advances after publish +
    load + validation succeed, and failed runs leave it untouched.
    """

    cursor_value: str | None
    source_scn: int | None
    load_id: str | None
    updated_at: dt.datetime | None


def get_watermark(contract: TableContract) -> Watermark:
    engine = loader_engine()
    with engine.connect() as connection:
        row = connection.execute(
            sa.text(
                """
                SELECT committed_cursor_value, committed_source_scn,
                       committed_load_id, updated_at
                  FROM control.replication_watermarks
                 WHERE source_schema = :schema AND source_table = :table
                """
            ),
            {"schema": contract.source_schema, "table": contract.source_table},
        ).fetchone()
    if row is None:
        return Watermark(None, None, None, None)
    return Watermark(
        cursor_value=row[0],
        source_scn=int(row[1]) if row[1] is not None else None,
        load_id=row[2],
        updated_at=row[3],
    )


def commit_watermark(
    contract: TableContract,
    *,
    cursor_value: str | None,
    source_scn: int,
    load_id: str,
) -> None:
    """The final step of a successful run — never called on failure."""
    engine = loader_engine()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO control.replication_watermarks
                    (source_schema, source_table, cursor_column,
                     committed_cursor_value, committed_source_scn,
                     committed_load_id, updated_at)
                VALUES (:schema, :table, :cursor_column, :cursor_value,
                        :scn, :load_id, now())
                ON CONFLICT (source_schema, source_table) DO UPDATE SET
                    cursor_column = EXCLUDED.cursor_column,
                    committed_cursor_value = EXCLUDED.committed_cursor_value,
                    committed_source_scn = EXCLUDED.committed_source_scn,
                    committed_load_id = EXCLUDED.committed_load_id,
                    updated_at = now()
                """
            ),
            {
                "schema": contract.source_schema,
                "table": contract.source_table,
                "cursor_column": contract.cursor_column,
                "cursor_value": cursor_value,
                "scn": source_scn,
                "load_id": load_id,
            },
        )
    logger.info(
        "watermark committed %s cursor=%s scn=%s load_id=%s",
        contract.qualified_name,
        cursor_value,
        source_scn,
        load_id,
    )


def new_run_id() -> str:
    return (
        dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ_")
        + uuid.uuid4().hex[:8]
    )


def start_run(run_id: str, kind: str, detail: dict[str, Any] | None = None) -> None:
    engine = loader_engine()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO control.replication_runs (run_id, kind, status, detail)
                VALUES (:run_id, :kind, 'running', CAST(:detail AS jsonb))
                ON CONFLICT (run_id) DO NOTHING
                """
            ),
            {"run_id": run_id, "kind": kind, "detail": json.dumps(detail or {})},
        )


def finish_run(run_id: str, status: str, detail: dict[str, Any] | None = None) -> None:
    engine = loader_engine()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                UPDATE control.replication_runs
                   SET status = :status,
                       completed_at = now(),
                       detail = coalesce(detail, '{}'::jsonb) || CAST(:detail AS jsonb)
                 WHERE run_id = :run_id
                """
            ),
            {"run_id": run_id, "status": status, "detail": json.dumps(detail or {})},
        )


def record_table_run(
    run_id: str,
    load_id: str,
    contract: TableContract,
    *,
    status: str,
    source_scn: int | None = None,
    cursor_lower: str | None = None,
    cursor_upper: str | None = None,
    rows_extracted: int | None = None,
    rows_written_to_lake: int | None = None,
    rows_loaded_to_postgres: int | None = None,
    rows_rejected: int = 0,
    error: str | None = None,
    completed: bool = False,
) -> None:
    engine = loader_engine()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO control.replication_table_runs
                    (run_id, load_id, source_schema, source_table, strategy,
                     status, source_scn, cursor_lower, cursor_upper,
                     rows_extracted, rows_written_to_lake,
                     rows_loaded_to_postgres, rows_rejected, error,
                     completed_at)
                VALUES
                    (:run_id, :load_id, :schema, :table, :strategy, :status,
                     :scn, :cursor_lower, :cursor_upper, :rows_extracted,
                     :rows_lake, :rows_pg, :rows_rejected, :error,
                     CASE WHEN :completed THEN now() END)
                ON CONFLICT (run_id, source_schema, source_table) DO UPDATE SET
                    status = EXCLUDED.status,
                    load_id = EXCLUDED.load_id,
                    source_scn = coalesce(EXCLUDED.source_scn, control.replication_table_runs.source_scn),
                    cursor_lower = coalesce(EXCLUDED.cursor_lower, control.replication_table_runs.cursor_lower),
                    cursor_upper = coalesce(EXCLUDED.cursor_upper, control.replication_table_runs.cursor_upper),
                    rows_extracted = coalesce(EXCLUDED.rows_extracted, control.replication_table_runs.rows_extracted),
                    rows_written_to_lake = coalesce(EXCLUDED.rows_written_to_lake, control.replication_table_runs.rows_written_to_lake),
                    rows_loaded_to_postgres = coalesce(EXCLUDED.rows_loaded_to_postgres, control.replication_table_runs.rows_loaded_to_postgres),
                    rows_rejected = EXCLUDED.rows_rejected,
                    error = EXCLUDED.error,
                    completed_at = coalesce(EXCLUDED.completed_at, control.replication_table_runs.completed_at)
                """
            ),
            {
                "run_id": run_id,
                "load_id": load_id,
                "schema": contract.source_schema,
                "table": contract.source_table,
                "strategy": contract.strategy.value,
                "status": status,
                "scn": source_scn,
                "cursor_lower": cursor_lower,
                "cursor_upper": cursor_upper,
                "rows_extracted": rows_extracted,
                "rows_lake": rows_written_to_lake,
                "rows_pg": rows_loaded_to_postgres,
                "rows_rejected": rows_rejected,
                "error": error,
                "completed": completed,
            },
        )


def record_schema_version(
    contract: TableContract, schema_hash: str, columns: list[dict[str, Any]]
) -> bool:
    """Store the observed schema fingerprint; return True if it is new."""
    engine = loader_engine()
    with engine.begin() as connection:
        known = connection.execute(
            sa.text(
                """
                SELECT count(*) FROM control.schema_versions
                 WHERE source_schema = :schema AND source_table = :table
                """
            ),
            {"schema": contract.source_schema, "table": contract.source_table},
        ).scalar()
        inserted = connection.execute(
            sa.text(
                """
                INSERT INTO control.schema_versions
                    (source_schema, source_table, schema_hash, columns)
                VALUES (:schema, :table, :hash, CAST(:columns AS jsonb))
                ON CONFLICT DO NOTHING
                RETURNING schema_hash
                """
            ),
            {
                "schema": contract.source_schema,
                "table": contract.source_table,
                "hash": schema_hash,
                "columns": json.dumps(columns),
            },
        ).fetchone()
    is_drift = bool(known) and inserted is not None
    if is_drift:
        logger.warning(
            "SCHEMA DRIFT detected for %s (new hash %s) — table paused for "
            "review (DCT-007/DCT-008)",
            contract.qualified_name,
            schema_hash,
        )
    return is_drift


def _lock_key(name: str) -> int:
    # zlib.crc32 is stable across processes, unlike hash() with PYTHONHASHSEED.
    return zlib.crc32(name.encode()) % (2**31)


def acquire_pipeline_lock(
    connection: sa.Connection, name: str = "smartforge_pipeline"
) -> bool:
    """Session-scoped advisory lock: single-flight for the whole pipeline."""
    return bool(
        connection.execute(
            sa.text("SELECT pg_try_advisory_lock(:key)"), {"key": _lock_key(name)}
        ).scalar()
    )


class PipelineBusyError(RuntimeError):
    """Another pipeline run holds the single-flight lock (INC-013)."""


@contextmanager
def pipeline_lock(name: str = "smartforge_pipeline") -> Iterator[None]:
    """Hold the pipeline single-flight lock for the duration of a code block.

    EVERY pipeline writer entry point — the dispatcher tick, operator CLI
    seed/sync, the API-triggered seed/sync background tasks, and the
    development sample seed — must run inside this guard so the
    single-writer guarantee (DDB-002, INC-013) holds no matter which
    process initiates the run. Non-reentrant by design: never nest it, and
    never call it from code the dispatcher already runs under its own lock.

    Raises PipelineBusyError immediately when the lock is held elsewhere
    (callers surface 409/skip — nobody queues behind a running pipeline).
    The session-scoped lock is released explicitly on exit and implicitly
    by connection close on any failure path.
    """
    engine = loader_engine()
    with engine.connect() as connection:
        if not acquire_pipeline_lock(connection, name):
            raise PipelineBusyError(
                "another pipeline run holds the single-flight lock; retry "
                "after it completes (monitor /platform/replication/runs)"
            )
        try:
            yield
        finally:
            connection.execute(
                sa.text("SELECT pg_advisory_unlock(:key)"), {"key": _lock_key(name)}
            )
