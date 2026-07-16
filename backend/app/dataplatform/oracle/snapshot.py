"""Consistent source boundaries (Specs §8.1, SEED-001/002).

Method A (preferred): capture one SCN and extract every table AS OF SCN.
The SCN is recorded in every manifest so all seed tables trace to the same
approved source boundary.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

import oracledb

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceBoundary:
    """A fixed extraction boundary: never chase a moving present (INC-002)."""

    scn: int
    source_timestamp_utc: dt.datetime
    captured_at_utc: dt.datetime

    @property
    def load_id(self) -> str:
        return f"{self.captured_at_utc.strftime('%Y%m%dT%H%M%SZ')}_{self.scn}"


def capture_boundary(connection: oracledb.Connection) -> SourceBoundary:
    """Capture the current SCN + source clock in one round trip each."""
    cursor = connection.cursor()
    try:
        try:
            cursor.execute("SELECT current_scn FROM v$database")
            scn = int(cursor.fetchone()[0])
        except oracledb.DatabaseError:
            # Fallback when V$DATABASE is not granted.
            cursor.execute("SELECT dbms_flashback.get_system_change_number FROM dual")
            scn = int(cursor.fetchone()[0])
        cursor.execute(
            "SELECT CAST(systimestamp AT TIME ZONE 'UTC' AS TIMESTAMP) FROM dual"
        )
        source_ts: dt.datetime = cursor.fetchone()[0]
    finally:
        cursor.close()
    boundary = SourceBoundary(
        scn=scn,
        source_timestamp_utc=source_ts.replace(tzinfo=dt.timezone.utc),
        captured_at_utc=dt.datetime.now(dt.timezone.utc),
    )
    logger.info("captured source boundary scn=%s source_ts=%s", scn, source_ts)
    return boundary


def supports_flashback(connection: oracledb.Connection, qualified_table: str) -> bool:
    """Probe whether AS OF SCN works for this table with current grants."""
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT current_scn FROM v$database")
        scn = int(cursor.fetchone()[0])
        cursor.execute(
            f"SELECT 1 FROM {qualified_table} AS OF SCN :scn WHERE ROWNUM = 1",  # noqa: S608
            {"scn": scn},
        )
        cursor.fetchall()
        return True
    except oracledb.DatabaseError as exc:
        logger.warning("flashback probe failed for %s: %s", qualified_table, exc)
        return False
    finally:
        cursor.close()
