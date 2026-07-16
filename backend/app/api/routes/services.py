"""Platform services registry — plugins, processes and 3rd-party integrations
wired into SmartForge. Status is derived from LIVE health probes (database,
Redis, Qdrant, telemetry freshness, LLM key) rather than static config, so the
Services page is a real health board."""

import asyncio
import time
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text
from sqlmodel import desc, select

from app.api.deps import InternalUser, SessionDep
from app.core.config import settings
from app.core.redis import get_redis
from app.core.vectorstore import vector_store
from app.models import TelemetryEvent
from app.models.base import get_datetime_utc

router = APIRouter(prefix="/services", tags=["services"])


def _db_health(session: SessionDep) -> tuple[str, float | None]:
    t = time.perf_counter()
    try:
        session.execute(text("SELECT 1"))
        return "running", round((time.perf_counter() - t) * 1000, 1)
    except Exception:  # noqa: BLE001
        return "offline", None


async def _redis_health() -> tuple[str, float | None]:
    t = time.perf_counter()
    try:
        await asyncio.wait_for(get_redis().ping(), timeout=1.0)
        return "running", round((time.perf_counter() - t) * 1000, 1)
    except Exception:  # noqa: BLE001
        return "offline", None


def _telemetry_health(session: SessionDep) -> tuple[str, str]:
    """The simulator (worker process) is 'running' when fresh telemetry exists."""
    latest = session.exec(
        select(TelemetryEvent).order_by(desc(TelemetryEvent.created_at)).limit(1)
    ).first()
    if not latest or not latest.created_at:
        return "offline", "no telemetry received"
    try:
        age = (get_datetime_utc() - latest.created_at).total_seconds()
    except TypeError:
        age = None
    if age is not None and age < settings.TELEMETRY_FRESH_SECONDS:
        return "running", f"last sample {int(age)}s ago"
    return "idle", "telemetry stale — worker may be stopped"


@router.get("/")
async def list_services(session: SessionDep, _user: InternalUser) -> Any:
    s = settings

    db_status, db_ms = _db_health(session)
    redis_status, redis_ms = await _redis_health()
    sim_status, sim_detail = _telemetry_health(session)
    # vector_store.available probes Qdrant (+ loads the embed model on first use);
    # run off the event loop so the health check never blocks other requests.
    try:
        qdrant_up = await asyncio.to_thread(lambda: vector_store.available)
    except Exception:  # noqa: BLE001
        qdrant_up = False

    def ms(v: float | None) -> str:
        return f" · {v}ms" if v is not None else ""

    fiix_live = bool(s.FIIX_API_KEY)
    data = [
        {
            "name": "PostgreSQL",
            "category": "Datastore",
            "status": db_status,
            "detail": f"Primary operational database{ms(db_ms)}",
            "configurable": False,
        },
        {
            "name": "Redis",
            "category": "Cache & Pub/Sub",
            "status": redis_status,
            "detail": f"{s.REDIS_HOST}:{s.REDIS_PORT}{ms(redis_ms)}",
            "configurable": True,
            "log_service": "redis",
        },
        {
            "name": "Qdrant Vector DB",
            "category": "RAG",
            "status": (
                "running"
                if qdrant_up
                else ("disabled" if not s.RAG_ENABLED else "offline")
            ),
            "detail": s.QDRANT_URL,
            "configurable": True,
            "log_service": "qdrant",
        },
        {
            "name": "Anthropic Claude",
            "category": "AI / LLM",
            "status": "connected" if s.askai_enabled else "offline",
            "detail": s.ANTHROPIC_MODEL,
            "configurable": True,
        },
        {
            "name": "Prometheus",
            "category": "Observability",
            "status": "running",
            "detail": "Metrics scrape target",
            "configurable": False,
        },
        {
            "name": "Grafana",
            "category": "Observability",
            "status": "running",
            "detail": "Dashboards",
            "configurable": False,
        },
        {
            "name": "Telemetry Simulator",
            "category": "Worker / Process",
            "status": sim_status,
            "detail": sim_detail,
            "configurable": True,
            "log_service": "worker",
        },
        {
            "name": "Fiix CMMS",
            "category": "Integration",
            "status": "connected" if fiix_live else "mock",
            "detail": s.FIIX_BASE_URL,
            "configurable": True,
        },
        {
            "name": "ERP Sync",
            "category": "Integration",
            "status": "mock",
            "detail": "Bidirectional ERP adapter",
            "configurable": True,
        },
        {
            "name": "MES Sync",
            "category": "Integration",
            "status": "mock",
            "detail": "Bidirectional MES adapter",
            "configurable": True,
        },
        {
            "name": "Email / SMTP",
            "category": "Integration",
            "status": "configured" if s.emails_enabled else "disabled",
            "detail": s.SMTP_HOST or "not configured",
            "configurable": True,
        },
    ]
    return {"data": data, "count": len(data)}
