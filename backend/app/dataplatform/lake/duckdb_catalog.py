"""DuckDB lake catalog.

DuckDB is the lake *query engine*; the durable lake is the published
Parquet tree. Only the ingestion process writes the catalog file (DDB-002);
API/BI consumers must open it read-only (DDB-003). Views point exclusively
at published paths — never staging or quarantine (DDB-004). Read-only query
execution is time-bounded via connection interruption (DDB-006).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import duckdb

from app.dataplatform.config import PlatformSettings, get_platform_settings
from app.dataplatform.oracle.metadata import validate_identifier
from app.dataplatform.registry import Registry

logger = logging.getLogger(__name__)


class LakeQueryTimeoutError(Exception):
    """A read-only lake query exceeded its bounded execution window (DDB-006).

    The message is deliberately free of SQL text, parameters, and paths so it
    can surface to API clients unmodified (OBS-006).
    """

    def __init__(self) -> None:
        super().__init__("Lake query exceeded the time limit")


def _apply_resource_limits(
    connection: duckdb.DuckDBPyConnection, settings: PlatformSettings
) -> None:
    # One analytical query must not exhaust the host (DDB-005).
    connection.execute(f"SET memory_limit = '{settings.DUCKDB_MEMORY_LIMIT}'")
    connection.execute(f"SET threads = {settings.DUCKDB_THREADS}")


@contextmanager
def writer_connection(
    settings: PlatformSettings | None = None,
) -> Iterator[duckdb.DuckDBPyConnection]:
    """The single controlled writer — ingestion/catalog refresh only."""
    settings = settings or get_platform_settings()
    settings.DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(settings.DUCKDB_PATH))
    try:
        _apply_resource_limits(connection, settings)
        yield connection
    finally:
        connection.close()


@contextmanager
def reader_connection(
    settings: PlatformSettings | None = None,
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Read-only connection for API workers (DDB-003)."""
    settings = settings or get_platform_settings()
    connection = duckdb.connect(str(settings.DUCKDB_PATH), read_only=True)
    try:
        _apply_resource_limits(connection, settings)
        yield connection
    finally:
        connection.close()


def refresh_catalog(
    registry: Registry, settings: PlatformSettings | None = None
) -> list[str]:
    """(Re)register raw views over every table's published Parquet tree.

    CREATE OR REPLACE VIEW is atomic per view (DDB-007); the view glob spans
    the snapshot and all increments — dbt staging models deduplicate to
    latest-row-per-key downstream.
    """
    settings = settings or get_platform_settings()
    registered: list[str] = []
    with writer_connection(settings) as connection:
        connection.execute("CREATE SCHEMA IF NOT EXISTS raw_oracle")
        for contract in registry.enabled():
            table_dir = contract.lake_table_dir(settings.lake_published_dir)
            if not any(table_dir.rglob("part-*.parquet")):
                continue
            view_name = validate_identifier(contract.destination_name)
            glob = (table_dir / "**" / "part-*.parquet").as_posix()
            connection.execute(
                f'CREATE OR REPLACE VIEW raw_oracle."{view_name}" AS '
                f"SELECT * FROM read_parquet('{glob}', "
                "hive_partitioning = true, union_by_name = true)"
            )
            registered.append(view_name)
    logger.info("duckdb catalog refreshed: %d raw views", len(registered))
    return registered


QueryRunner = Callable[..., tuple[list[str], list[tuple[Any, ...]]]]


@contextmanager
def read_scope(
    settings: PlatformSettings | None = None,
    *,
    timeout_ms: int | None = None,
) -> Iterator[QueryRunner]:
    """One read-only connection + one watchdog for a whole request's worth
    of queries. A governed lake read runs several internally-built
    statements (column probe, count, page); scoping them to a single
    catalog open keeps per-request cost flat under concurrency instead of
    paying the file-open/attach price per statement. The shared execution
    budget (DDB-006) covers the scope: the watchdog interrupts the
    connection after API_STATEMENT_TIMEOUT_MS and the interruption
    surfaces as LakeQueryTimeoutError with a safe message.
    """
    resolved = settings or get_platform_settings()
    timeout_seconds = (
        timeout_ms if timeout_ms is not None else resolved.API_STATEMENT_TIMEOUT_MS
    ) / 1000.0
    with reader_connection(resolved) as connection:
        watchdog = threading.Timer(timeout_seconds, connection.interrupt)
        watchdog.daemon = True
        watchdog.start()

        def run(
            sql: str, params: list[Any] | None = None
        ) -> tuple[list[str], list[tuple[Any, ...]]]:
            try:
                cursor = connection.execute(sql, params or [])
                column_names = [d[0] for d in cursor.description or []]
                return column_names, cursor.fetchall()
            except duckdb.InterruptException as exc:
                logger.warning(
                    "lake query interrupted after %.3fs (DDB-006)",
                    timeout_seconds,
                )
                raise LakeQueryTimeoutError() from exc

        try:
            yield run
        finally:
            watchdog.cancel()


def query_readonly(
    sql: str,
    params: list[Any] | None = None,
    settings: PlatformSettings | None = None,
    *,
    timeout_ms: int | None = None,
) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Execute one internally-built, parameterized query read-only —
    a single-statement read_scope (same bounded-execution guarantees)."""
    with read_scope(settings, timeout_ms=timeout_ms) as run:
        return run(sql, params)


def list_relations(settings: PlatformSettings | None = None) -> list[dict[str, str]]:
    """Enumerate lake schemas/relations for the catalog endpoint."""
    with reader_connection(settings) as connection:
        rows = connection.execute(
            """
            SELECT table_schema, table_name, table_type
              FROM information_schema.tables
             WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
             ORDER BY table_schema, table_name
            """
        ).fetchall()
    return [{"schema": r[0], "name": r[1], "type": r[2]} for r in rows]
