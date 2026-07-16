"""Read-only Oracle (omega) connectivity.

python-oracledb THIN mode only — no Instant Client (Specs §3.2, D8).
The pool is deliberately small: we are a tenant on the transactional
system and must protect it (ORA-007).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import oracledb

from app.dataplatform.config import PlatformSettings, get_platform_settings

logger = logging.getLogger(__name__)

_pool: oracledb.ConnectionPool | None = None


def create_pool(settings: PlatformSettings | None = None) -> oracledb.ConnectionPool:
    settings = settings or get_platform_settings()
    dsn = oracledb.makedsn(**settings.oracle_dsn_params)  # type: ignore[arg-type]
    pool = oracledb.create_pool(
        user=settings.OMEGA_ORACLE_USER,
        password=settings.OMEGA_ORACLE_PASSWORD,
        dsn=dsn,
        min=settings.OMEGA_ORACLE_POOL_MIN,
        max=settings.OMEGA_ORACLE_POOL_MAX,
        increment=1,
        getmode=oracledb.POOL_GETMODE_WAIT,
        ping_interval=60,
    )
    logger.info(
        "omega oracle pool created host=%s service=%s user=%s (read-only identity)",
        settings.OMEGA_ORACLE_HOST,
        settings.OMEGA_ORACLE_SERVICE_NAME or settings.OMEGA_ORACLE_SID,
        settings.OMEGA_ORACLE_USER,
    )
    return pool


def get_pool() -> oracledb.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = create_pool()
    return _pool


@contextmanager
def oracle_connection() -> Iterator[oracledb.Connection]:
    """Acquire a pooled connection with a bounded call timeout."""
    settings = get_platform_settings()
    pool = get_pool()
    connection = pool.acquire()
    try:
        connection.call_timeout = settings.OMEGA_ORACLE_CALL_TIMEOUT_SECONDS * 1000
        yield connection
    finally:
        pool.release(connection)


def verify_read_only(connection: oracledb.Connection) -> dict[str, Any]:
    """Prove the extraction identity cannot write (ORA-003).

    Dictionary-based verification — no probe statement is ever executed
    against the source. Two static, bound-free catalog queries run:
      1. session_privs — fails closed on any system-wide write privilege
         (INSERT/UPDATE/DELETE/CREATE/DROP/ALTER ANY TABLE);
      2. all_tab_privs for the current USER — fails closed on any
         object-level write grant (INSERT/UPDATE/DELETE/ALTER/INDEX/
         REFERENCES on any table).
    Returns both privilege sets as evidence for the audit trail; raises
    PermissionError naming every offending grant (ORA-002/ORA-003).
    """
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT privilege FROM session_privs ORDER BY privilege")
        privileges = [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()

    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT table_name, privilege
              FROM all_tab_privs
             WHERE grantee = USER
               AND privilege IN
                   ('INSERT', 'UPDATE', 'DELETE', 'ALTER', 'INDEX', 'REFERENCES')
             ORDER BY table_name, privilege
            """
        )
        object_write_grants = [f"{row[0]}:{row[1]}" for row in cursor.fetchall()]
    finally:
        cursor.close()

    forbidden = {
        "INSERT ANY TABLE",
        "UPDATE ANY TABLE",
        "DELETE ANY TABLE",
        "CREATE ANY TABLE",
        "DROP ANY TABLE",
        "ALTER ANY TABLE",
    }
    held_forbidden = sorted(forbidden.intersection(privileges))
    if held_forbidden or object_write_grants:
        raise PermissionError(
            "Omega extraction identity holds write privileges — system: "
            f"{held_forbidden}, object grants: {object_write_grants}; "
            "refusing to run. The account must be read-only "
            "(Checklist ORA-002/ORA-003)."
        )
    return {
        "session_privileges": privileges,
        "write_privileges_found": [],
        "object_write_grants": object_write_grants,
    }


def ping() -> bool:
    try:
        with oracle_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT 1 FROM dual")
                cursor.fetchone()
            finally:
                cursor.close()
        return True
    except Exception:  # pragma: no cover - connectivity probe
        logger.exception("omega oracle ping failed")
        return False
