"""Per-table freshness (Specs §21.3, Checklist OBS-003/DQ-014).

Freshness derives from the committed watermark — the last *validated*
publication — so a dead scheduler or a silently failing job surfaces as
stale data (the dead-man's-switch signal), never as false health.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import sqlalchemy as sa

from app.dataplatform.config import get_platform_settings
from app.dataplatform.registry import Cadence, Registry, load_registry
from app.dataplatform.warehouse.postgres import api_engine


def _thresholds(cadence: Cadence) -> tuple[int, int]:
    settings = get_platform_settings()
    if cadence is Cadence.hourly:
        return (
            settings.FRESHNESS_HOURLY_WARN_MINUTES,
            settings.FRESHNESS_HOURLY_ERROR_MINUTES,
        )
    if cadence is Cadence.daily:
        return (
            settings.FRESHNESS_DAILY_WARN_MINUTES,
            settings.FRESHNESS_DAILY_ERROR_MINUTES,
        )
    return 60 * 24 * 8, 60 * 24 * 10  # weekly: warn 8d, error 10d


def table_freshness(registry: Registry | None = None) -> list[dict[str, Any]]:
    registry = registry or load_registry()
    engine = api_engine()
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                """
                SELECT source_schema, source_table, committed_cursor_value,
                       committed_source_scn, committed_load_id, updated_at
                  FROM control.replication_watermarks
                """
            )
        ).fetchall()
    by_table = {(r[0], r[1]): r for r in rows}
    now = dt.datetime.now(dt.timezone.utc)

    report: list[dict[str, Any]] = []
    for contract in registry.enabled():
        warn_min, error_min = _thresholds(contract.cadence)
        row = by_table.get((contract.source_schema, contract.source_table))
        if row is None:
            report.append(
                {
                    "table": contract.qualified_name,
                    "destination": contract.destination_name,
                    "cadence": contract.cadence.value,
                    "status": "never_loaded",
                    "lag_minutes": None,
                    "last_load_id": None,
                    "last_published_at": None,
                    "source_scn": None,
                }
            )
            continue
        updated_at: dt.datetime = row[5]
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=dt.timezone.utc)
        lag_minutes = (now - updated_at).total_seconds() / 60
        status = "fresh"
        if lag_minutes > error_min:
            status = "stale"
        elif lag_minutes > warn_min:
            status = "warning"
        report.append(
            {
                "table": contract.qualified_name,
                "destination": contract.destination_name,
                "cadence": contract.cadence.value,
                "status": status,
                "lag_minutes": round(lag_minutes, 1),
                "last_load_id": row[4],
                "last_published_at": updated_at.isoformat(),
                "source_scn": int(row[3]) if row[3] is not None else None,
            }
        )
    return report
