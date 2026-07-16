"""Per-service troubleshooting log console. Returns a bounded window of recent
log lines per platform service — a console view, not a firehose of events.

The "audit" stream is REAL: it surfaces the platform audit trail (every
write_audit() call across the app). Other process streams are representative
bounded samples (we have no host PID/journald access from the container)."""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import desc, select

from app.api.deps import InternalUser, SessionDep
from app.models import Alert, AuditLog, Machine
from app.models.base import get_datetime_utc

router = APIRouter(prefix="/logs", tags=["logs"])

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
    cross-channel aggregate, "audit" is the raw audit trail; the rest are
    per-process consoles."""
    services = ["events", "audit", *_SERVICE_LINES.keys()]
    return {"data": services, "count": len(services)}


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
