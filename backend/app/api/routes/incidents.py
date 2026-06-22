"""Incident & RCA APIs (spec §3D)."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import desc, select

from app.api.deps import InternalUser, SessionDep
from app.models import (
    Incident,
    IncidentCreate,
    IncidentPublic,
    IncidentsPublic,
    RcaRecord,
    RcaRecordCreate,
    RcaRecordPublic,
    RcaRecordsPublic,
)
from app.services.common import list_and_count, write_audit

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("/", response_model=IncidentsPublic)
def read_incidents(session: SessionDep, _user: InternalUser) -> Any:
    rows, count = list_and_count(
        session, Incident, order_by=desc(Incident.created_at)
    )
    return IncidentsPublic(data=rows, count=count)


@router.post("/", response_model=IncidentPublic)
def create_incident(
    payload: IncidentCreate, session: SessionDep, user: InternalUser
) -> Any:
    inc = Incident.model_validate(payload)
    session.add(inc)
    session.commit()
    session.refresh(inc)
    write_audit(session, actor=user, action="incident.create",
                entity_type="incident", entity_id=inc.id)
    return inc


@router.get("/{incident_id}/rca", response_model=RcaRecordsPublic)
def read_rca(incident_id: uuid.UUID, session: SessionDep, _user: InternalUser) -> Any:
    rows = list(session.exec(
        select(RcaRecord).where(RcaRecord.incident_id == incident_id)
    ).all())
    return RcaRecordsPublic(data=rows, count=len(rows))


@router.post("/{incident_id}/rca", response_model=RcaRecordPublic)
def create_rca(
    incident_id: uuid.UUID, payload: RcaRecordCreate,
    session: SessionDep, user: InternalUser,
) -> Any:
    if not session.get(Incident, incident_id):
        raise HTTPException(status_code=404, detail="Incident not found")
    rca = RcaRecord.model_validate(payload, update={"incident_id": incident_id})
    session.add(rca)
    session.commit()
    session.refresh(rca)
    write_audit(session, actor=user, action="rca.create",
                entity_type="rca_record", entity_id=rca.id)
    return rca
