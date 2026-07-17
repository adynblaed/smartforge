"""Per-service troubleshooting log console. Returns a bounded window of recent
log lines per platform service — a console view, not a firehose of events.

The "audit" stream is REAL: it surfaces the platform audit trail (every
write_audit() call across the app). The "warehouse" and "lake" streams are
REAL too — they read the data platform's own control/audit tables
(replication runs, published manifests, reconciliation evidence) through
the read-only warehouse API role. Other process streams are representative
bounded samples (we have no host PID/journald access from the container)."""

from datetime import timedelta
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, desc, select

from app.api.deps import InternalUser, SessionDep
from app.core.features import require_feature
from app.models import Alert, AuditLog, Machine
from app.models.base import get_datetime_utc

# Developer-tier gate (logs_console): the per-service console exposes the
# audit trail and operational internals — server-enforced, in parity with
# the frontend nav gate.
router = APIRouter(
    prefix="/logs",
    tags=["logs"],
    dependencies=[Depends(require_feature("logs_console"))],
)

# Representative recent log lines per service (level, message). Bounded so the
# console never floods with live events/queue traffic.
_SERVICE_LINES: dict[str, list[tuple[str, str]]] = {
    "backend": [
        ("INFO", "GET /api/v1/command-center 200"),
        ("INFO", "POST /api/v1/ask-ai/forge 200"),
        ("INFO", "GET /api/v1/machines/ 200"),
        ("INFO", "auth: access token verified"),
        ("WARN", "slow query: telemetry aggregate 412ms"),
        ("INFO", "GET /api/v1/tickets/ 200"),
        ("INFO", "WebSocket /api/v1/ws/telemetry accepted"),
    ],
    "worker": [
        ("INFO", "telemetry tick — 3 machines sampled"),
        ("INFO", "alert rules evaluated"),
        ("INFO", "published smartforge:telemetry"),
        ("WARN", "cnc-01 vibration 0.71 > 0.60 threshold"),
        ("INFO", "machine health scores recomputed"),
        ("INFO", "order stage advanced — SO-104"),
    ],
    "db": [
        ("INFO", "checkpoint complete"),
        ("INFO", "autovacuum: telemetry_events"),
        ("WARN", "connection pool 18/20 in use"),
        ("INFO", "analyze: machine_health_scores"),
    ],
    "redis": [
        ("INFO", "pubsub channel smartforge:telemetry"),
        ("INFO", "BGSAVE complete (0.04s)"),
        ("INFO", "client connected"),
    ],
    "qdrant": [
        ("INFO", "collection knowledge_bases loaded"),
        ("INFO", "search — 5 results in 12ms"),
        ("INFO", "upsert 1 point"),
    ],
    "frontend": [
        ("INFO", "nginx 200 /command-center"),
        ("INFO", "nginx 200 /api/v1/machines/"),
        ("INFO", "nginx 304 /assets/index.js"),
    ],
}

# Audit actions whose log line should read as a warning rather than info.
_WARN_HINTS = ("delete", "reject", "fail", "escalat", "resolve")


def _audit_source(action: str) -> str:
    """Map an audit action to a human source channel for the events stream."""
    a = action.lower()
    if a.startswith("forge"):
        return "ForgeAI"
    if "knowledge_base" in a:
        return "Forge Facts"
    if "sync_rag" in a:
        return "RAG"
    if a.startswith("askai"):
        return "AskAI"
    if "ticket" in a:
        return "Ticketing"
    if "work_order" in a:
        return "Work Orders"
    if "incident" in a:
        return "Incidents"
    if "quote" in a:
        return "Quotes"
    if "purchase" in a or "order" in a:
        return "Order Tracker"
    if "recommendation" in a or "config" in a:
        return "Optimization"
    if "defect" in a or "inspection" in a:
        return "Quality"
    return "System"


@router.get("/services")
def log_services(_session: SessionDep, _user: InternalUser) -> Any:
    """Active platform services/processes that expose a log stream. "events" is a
    cross-channel aggregate, "audit" is the raw audit trail, "warehouse" and
    "lake" surface the data platform's control/audit tables; the rest are
    per-process consoles."""
    services = ["events", "audit", *_SERVICE_LINES.keys(), "warehouse", "lake"]
    return {"data": services, "count": len(services)}


def _platform_read(sql: str, limit: int) -> list[dict[str, Any]]:
    """Bounded read-only query against the warehouse control/audit schemas
    (same READ ONLY + statement-timeout discipline as /platform, API-007/008)."""
    from app.dataplatform.config import get_platform_settings
    from app.dataplatform.warehouse.postgres import api_engine

    with api_engine().connect() as connection:
        connection.execute(sa.text("SET TRANSACTION READ ONLY"))
        connection.execute(
            sa.text(
                f"SET statement_timeout = "
                f"{get_platform_settings().API_STATEMENT_TIMEOUT_MS}"
            )
        )
        rows = connection.execute(sa.text(sql), {"limit": limit}).mappings().all()
    return [dict(r) for r in rows]


def _not_provisioned_line() -> list[dict[str, Any]]:
    return [
        {
            "ts": get_datetime_utc().isoformat(),
            "level": "WARN",
            "message": (
                "analytics stores not provisioned — run "
                "`python -m app.dataplatform.cli bootstrap` (then seed)"
            ),
        }
    ]


def _sync_trigger_events(
    session: SessionDep, limit: int
) -> list[tuple[Any, str, str]]:
    """User-attributed sync triggers AND terminal sync failures from the
    audit trail — woven into both the warehouse and lake consoles so every
    operator-executed sync/merge names WHO ran it (and whether it exhausted
    its retries), in parity with the Omega catalogue and audit stream."""
    rows = session.exec(
        select(AuditLog)
        .where(
            col(AuditLog.action).in_(
                [
                    "platform_table_sync_triggered",
                    "platform_table_sync_failed",
                ]
            )
        )
        .order_by(desc(AuditLog.created_at))
        .limit(limit)
    ).all()
    events: list[tuple[Any, str, str]] = []
    for r in rows:
        if r.action == "platform_table_sync_failed":
            events.append((r.created_at, "ERROR", f"sync {r.detail or ''}"))
        else:
            events.append(
                (
                    r.created_at,
                    "INFO",
                    f"sync {r.detail or 'tables'} triggered by "
                    f"{r.actor_email or 'system'}",
                )
            )
    return events


def _warehouse_lines(session: SessionDep, limit: int) -> list[dict[str, Any]]:
    """Real warehouse-service console: pipeline runs, per-table loads into
    raw_oracle, and reconciliation failures — oldest → newest."""
    try:
        runs = _platform_read(
            """
            SELECT run_id, kind, status, started_at, completed_at
              FROM control.replication_runs
             ORDER BY started_at DESC LIMIT :limit
            """,
            max(1, limit // 3),
        )
        table_runs = _platform_read(
            """
            SELECT run_id, source_schema, source_table, strategy, status,
                   rows_loaded_to_postgres, error, started_at
              FROM control.replication_table_runs
             ORDER BY started_at DESC LIMIT :limit
            """,
            limit,
        )
        recon = _platform_read(
            """
            SELECT source_schema, source_table, check_name, passed, checked_at
              FROM audit.reconciliation_results
             WHERE NOT passed
             ORDER BY checked_at DESC LIMIT :limit
            """,
            max(1, limit // 3),
        )
    except Exception:
        return _not_provisioned_line()

    events: list[tuple[Any, str, str]] = []
    for r in runs:
        level = "ERROR" if r["status"] == "failed" else "INFO"
        events.append(
            (
                r["completed_at"] or r["started_at"],
                level,
                f"run {str(r['run_id'])[:12]} · {r['kind']} {r['status']}",
            )
        )
    for r in table_runs:
        if r["error"]:
            events.append(
                (
                    r["started_at"],
                    "ERROR",
                    f"{r['source_schema']}.{r['source_table']} failed — {r['error']}",
                )
            )
        else:
            rows_loaded = r["rows_loaded_to_postgres"] or 0
            events.append(
                (
                    r["started_at"],
                    "INFO",
                    f"merged raw_oracle.{str(r['source_table']).lower()} — "
                    f"{rows_loaded} rows ({r['strategy']})",
                )
            )
    for r in recon:
        events.append(
            (
                r["checked_at"],
                "WARN",
                f"reconciliation {r['check_name']} FAILED for "
                f"{r['source_schema']}.{r['source_table']}",
            )
        )
    events.extend(_sync_trigger_events(session, max(1, limit // 3)))
    events.sort(key=lambda e: (e[0] is not None, e[0]))
    now = get_datetime_utc()
    return [
        {"ts": (ts or now).isoformat(), "level": level, "message": msg}
        for ts, level, msg in events[-limit:]
    ]


def _lake_lines(session: SessionDep, limit: int) -> list[dict[str, Any]]:
    """Real lake-service console: immutable Parquet publications from the
    manifest ledger — oldest → newest."""
    try:
        manifests = _platform_read(
            """
            SELECT load_id, source_schema, source_table, source_scn,
                   row_count, file_count, status, published_at
              FROM control.replication_manifests
             ORDER BY published_at DESC LIMIT :limit
            """,
            limit,
        )
    except Exception:
        return _not_provisioned_line()

    events: list[tuple[Any, str, str]] = []
    for m in manifests:
        level = "INFO" if m["status"] in ("loaded", "published") else "WARN"
        events.append(
            (
                m["published_at"],
                level,
                f"published {str(m['source_schema']).lower()}."
                f"{str(m['source_table']).lower()} load {m['load_id']} — "
                f"{m['row_count'] or 0} rows, {m['file_count'] or 0} file(s), "
                f"scn {m['source_scn']} [{m['status']}]",
            )
        )
    events.extend(_sync_trigger_events(session, max(1, limit // 3)))
    events.sort(key=lambda e: (e[0] is not None, e[0]))
    now = get_datetime_utc()
    return [
        {"ts": (ts or now).isoformat(), "level": level, "message": msg}
        for ts, level, msg in events[-limit:]
    ]


def _events_lines(session: SessionDep, limit: int) -> list[dict[str, Any]]:
    """Aggregate the most relevant live channels — audit actions (ForgeAI, POs,
    work orders, tickets, incidents, quotes, Forge Facts/SOPs, order tracker) +
    machine alerts — into one time-stepped, source-referenced event log."""
    events: list[tuple[Any, str, str]] = []  # (ts, level, message)

    audits = session.exec(
        select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
    ).all()
    for r in audits:
        src = _audit_source(r.action)
        level = "WARN" if any(h in r.action for h in _WARN_HINTS) else "INFO"
        who = r.actor_email or "system"
        detail = f" — {r.detail}" if r.detail else ""
        events.append((r.created_at, level, f"[{src}] {r.action}{detail} ({who})"))

    # Machine channel: recent alerts (with machine code as the source ref).
    codes = {m.id: m.code for m in session.exec(select(Machine)).all()}
    alerts = session.exec(
        select(Alert).order_by(desc(Alert.created_at)).limit(limit)
    ).all()
    for a in alerts:
        level = "ERROR" if a.severity.value in ("critical", "high") else "WARN"
        code = codes.get(a.machine_id, "machine")
        events.append((a.created_at, level, f"[Machine {code}] {a.message}"))

    # Newest first, then present oldest → newest like a tail.
    events.sort(key=lambda e: (e[0] is not None, e[0]), reverse=True)
    top = events[:limit]
    top.reverse()
    now = get_datetime_utc()
    return [
        {"ts": (ts or now).isoformat(), "level": level, "message": msg}
        for ts, level, msg in top
    ]


def _audit_lines(session: SessionDep, limit: int) -> list[dict[str, Any]]:
    rows = session.exec(
        select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
    ).all()
    out: list[dict[str, Any]] = []
    for r in reversed(rows):  # oldest → newest
        level = "WARN" if any(h in r.action for h in _WARN_HINTS) else "INFO"
        who = r.actor_email or "system"
        target = f" {r.entity_type}" + (f"/{r.entity_id}" if r.entity_id else "")
        detail = f" — {r.detail}" if r.detail else ""
        out.append(
            {
                "ts": (r.created_at or get_datetime_utc()).isoformat(),
                "level": level,
                "message": f"{who} · {r.action}{target}{detail}",
            }
        )
    return out


@router.get("/{service}")
def service_logs(
    service: str, session: SessionDep, _user: InternalUser, limit: int = 60
) -> Any:
    n = max(1, min(limit, 80))
    if service == "events":
        lines = _events_lines(session, n)
        return {"service": service, "data": lines, "count": len(lines)}
    if service == "audit":
        lines = _audit_lines(session, n)
        return {"service": service, "data": lines, "count": len(lines)}
    if service == "warehouse":
        lines = _warehouse_lines(session, n)
        return {"service": service, "data": lines, "count": len(lines)}
    if service == "lake":
        lines = _lake_lines(session, n)
        return {"service": service, "data": lines, "count": len(lines)}

    tmpl = _SERVICE_LINES.get(service)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Unknown service")
    now = get_datetime_utc()
    lines = []
    for i in range(n):
        level, msg = tmpl[(i * 7 + len(service)) % len(tmpl)]
        ts = now - timedelta(seconds=i * 13 + (i % 5))
        lines.append({"ts": ts.isoformat(), "level": level, "message": msg})
    lines.reverse()  # oldest → newest
    return {"service": service, "data": lines, "count": len(lines)}
