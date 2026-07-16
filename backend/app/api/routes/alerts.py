"""Alert management APIs (spec §6 Alert APIs, Module 1B)."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import desc

from app.api.deps import InternalUser, SessionDep
from app.models import Alert, AlertPublic, AlertsPublic, AlertStatus
from app.models.base import get_datetime_utc
from app.services.common import list_and_count, write_audit

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/", response_model=AlertsPublic)
def read_alerts(
    session: SessionDep,
    _user: InternalUser,
    skip: int = 0,
    limit: int = 100,
    status: AlertStatus | None = None,
) -> Any:
    where = (Alert.status == status) if status else None
    rows, count = list_and_count(
        session,
        Alert,
        skip=skip,
        limit=limit,
        where=where,
        order_by=desc(Alert.created_at),
    )
    return AlertsPublic(data=rows, count=count)


@router.post("/{alert_id}/acknowledge", response_model=AlertPublic)
def acknowledge_alert(
    alert_id: uuid.UUID, session: SessionDep, user: InternalUser
) -> Any:
    alert = session.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = AlertStatus.acknowledged
    alert.acknowledged_at = get_datetime_utc()
    session.add(alert)
    session.commit()
    session.refresh(alert)
    write_audit(
        session,
        actor=user,
        action="alert.acknowledge",
        entity_type="alert",
        entity_id=alert.id,
    )
    return alert


@router.post("/{alert_id}/resolve", response_model=AlertPublic)
def resolve_alert(alert_id: uuid.UUID, session: SessionDep, user: InternalUser) -> Any:
    alert = session.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = AlertStatus.resolved
    alert.resolved_at = get_datetime_utc()
    session.add(alert)
    session.commit()
    session.refresh(alert)
    write_audit(
        session,
        actor=user,
        action="alert.resolve",
        entity_type="alert",
        entity_id=alert.id,
    )
    return alert
