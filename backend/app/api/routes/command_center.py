"""Executive aggregation, KPIs, and Prometheus metrics (spec §3B/§3E/§8)."""

import secrets
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from sqlmodel import func, select

from app.api.deps import InternalUser, SessionDep
from app.core.config import settings
from app.exporters import prometheus as prom
from app.models import (
    Alert,
    AlertStatus,
    CustomerOrder,
    FactoriesPublic,
    Factory,
    InventoryItem,
    Line,
    LinesPublic,
    Machine,
    OeeMetric,
    WorkOrder,
    WorkOrderStatus,
)

router = APIRouter(tags=["command-center"])


def _kpis(session: SessionDep) -> dict[str, Any]:
    machines = list(session.exec(select(Machine)).all())
    avg_health = (
        round(sum(m.health_score for m in machines) / len(machines), 1)
        if machines
        else 0.0
    )
    open_wos = session.exec(
        select(func.count())
        .select_from(WorkOrder)
        .where(WorkOrder.status != WorkOrderStatus.completed)
    ).one()
    active_alerts = session.exec(
        select(func.count())
        .select_from(Alert)
        .where(Alert.status == AlertStatus.active)
    ).one()
    oee_rows = list(session.exec(select(OeeMetric)).all())
    avg_oee = (
        round(sum(o.oee for o in oee_rows) / len(oee_rows), 4) if oee_rows else 0.0
    )
    avg_scrap = (
        round(sum(o.scrap_rate for o in oee_rows) / len(oee_rows), 4)
        if oee_rows
        else 0.0
    )
    downtime = sum(o.downtime_minutes for o in oee_rows)
    delayed_orders = session.exec(
        select(func.count())
        .select_from(CustomerOrder)
        .where(CustomerOrder.delayed == True)  # noqa: E712
    ).one()
    inv = list(session.exec(select(InventoryItem)).all())
    below = sum(1 for i in inv if i.quantity < i.reorder_threshold)
    return {
        "avg_machine_health": avg_health,
        "open_work_orders": open_wos,
        "active_alerts": active_alerts,
        "avg_oee": avg_oee,
        "avg_scrap_rate": avg_scrap,
        "unplanned_downtime_minutes": downtime,
        "delayed_orders": delayed_orders,
        "inventory_below_threshold": below,
        "throughput": round(sum(o.throughput for o in oee_rows), 1),
    }


@router.get("/factories", response_model=FactoriesPublic)
def read_factories(session: SessionDep, _user: InternalUser) -> Any:
    rows = list(session.exec(select(Factory)).all())
    return FactoriesPublic(data=list(rows), count=len(rows))


@router.get("/lines", response_model=LinesPublic)
def read_lines(session: SessionDep, _user: InternalUser) -> Any:
    rows = list(session.exec(select(Line)).all())
    return LinesPublic(data=list(rows), count=len(rows))


@router.get("/factory/kpis")
def factory_kpis(session: SessionDep, _user: InternalUser) -> Any:
    return _kpis(session)


@router.get("/command-center")
def command_center(session: SessionDep, _user: InternalUser) -> Any:
    kpis = _kpis(session)
    machines = list(session.exec(select(Machine)).all())
    at_risk = sorted(machines, key=lambda m: m.health_score)[:3]
    risk_alerts = list(
        session.exec(
            select(Alert).where(Alert.status == AlertStatus.active).limit(5)
        ).all()
    )
    return {
        "factory_health_summary": {
            "avg_health": kpis["avg_machine_health"],
            "machines": len(machines),
            "at_risk": [{"code": m.code, "health": m.health_score} for m in at_risk],
        },
        "kpis": kpis,
        "risk_alerts": risk_alerts,
        "production_status": {
            "avg_oee": kpis["avg_oee"],
            "throughput": kpis["throughput"],
        },
        "maintenance_status": {
            "open_work_orders": kpis["open_work_orders"],
            "active_alerts": kpis["active_alerts"],
        },
        "customer_impact": {"delayed_orders": kpis["delayed_orders"]},
    }


def refresh_gauges(session: Any) -> None:
    """Push current DB state into Prometheus gauges before scraping."""
    for m in session.exec(select(Machine)).all():
        mid = m.code
        prom.MACHINE_HEALTH.labels(machine_id=mid).set(m.health_score)
    for o in session.exec(select(OeeMetric)).all():
        prom.OEE_PERCENT.labels(line_id=str(o.line_id)).set(o.oee * 100)
        prom.SCRAP_RATE.labels(line_id=str(o.line_id)).set(o.scrap_rate * 100)
    kpis = _kpis(session)
    prom.OPEN_WORK_ORDERS.set(kpis["open_work_orders"])
    prom.UNPLANNED_DOWNTIME.set(kpis["unplanned_downtime_minutes"])
    prom.ORDERS_DELAYED.set(kpis["delayed_orders"])
    prom.INVENTORY_BELOW_THRESHOLD.set(kpis["inventory_below_threshold"])


# Scrape hardening: gauge refresh runs full-table aggregates, so it is
# throttled to once per window regardless of scrape (or abuse) rate — the
# endpoint itself must stay cheap because it is rate-limit-exempt and, on
# in-network deployments, unauthenticated. State is per process; each
# uvicorn worker refreshes its own registry on its own clock.
_METRICS_REFRESH_WINDOW_SECONDS = 10.0
_metrics_refresh_lock = threading.Lock()
_metrics_last_refresh = 0.0


@router.get("/metrics")
def metrics(session: SessionDep, request: Request) -> Response:
    """Prometheus scrape endpoint.

    Auth: open by default for in-network scrapers; set METRICS_BEARER_TOKEN
    to require `Authorization: Bearer <token>` (defense for deployments
    where the API port is reachable beyond the scrape network)."""
    expected = settings.METRICS_BEARER_TOKEN
    if expected:
        supplied = request.headers.get("Authorization", "")
        if not secrets.compare_digest(supplied, f"Bearer {expected}"):
            raise HTTPException(status_code=401, detail="Not authenticated")
    global _metrics_last_refresh
    now = time.monotonic()
    with _metrics_refresh_lock:
        due = now - _metrics_last_refresh >= _METRICS_REFRESH_WINDOW_SECONDS
        if due:
            _metrics_last_refresh = now
    if due:
        refresh_gauges(session)
    return Response(content=prom.render_metrics(), media_type="text/plain")
