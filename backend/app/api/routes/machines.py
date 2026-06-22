"""Machine intelligence APIs (spec §6 Machine APIs)."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import desc, select

from app.api.deps import InternalUser, SessionDep
from app.core import redis
from app.models import (
    AskRequest,
    AskResponse,
    Machine,
    MachineHealthScore,
    MachineHealthScorePublic,
    MachinePublic,
    MachinesPublic,
    TelemetryEvent,
    TelemetryEventCreate,
    TelemetryEventPublic,
    TelemetryEventsPublic,
)
from app.services import askai, machine_intelligence
from app.services.common import list_and_count

router = APIRouter(prefix="/machines", tags=["machines"])


@router.get("/", response_model=MachinesPublic)
def read_machines(
    session: SessionDep, _user: InternalUser, skip: int = 0, limit: int = 100
) -> Any:
    rows, count = list_and_count(session, Machine, skip=skip, limit=limit)
    return MachinesPublic(data=rows, count=count)


@router.get("/{machine_id}", response_model=MachinePublic)
def read_machine(machine_id: uuid.UUID, session: SessionDep, _user: InternalUser) -> Any:
    machine = session.get(Machine, machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    return machine


@router.get("/{machine_id}/telemetry", response_model=TelemetryEventsPublic)
def read_telemetry(
    machine_id: uuid.UUID, session: SessionDep, _user: InternalUser, limit: int = 50
) -> Any:
    stmt = (
        select(TelemetryEvent)
        .where(TelemetryEvent.machine_id == machine_id)
        .order_by(desc(TelemetryEvent.created_at))
        .limit(limit)
    )
    rows = list(session.exec(stmt).all())
    return TelemetryEventsPublic(data=rows, count=len(rows))


@router.get("/{machine_id}/health", response_model=MachineHealthScorePublic)
def read_health(machine_id: uuid.UUID, session: SessionDep, _user: InternalUser) -> Any:
    stmt = (
        select(MachineHealthScore)
        .where(MachineHealthScore.machine_id == machine_id)
        .order_by(desc(MachineHealthScore.created_at))
        .limit(1)
    )
    score = session.exec(stmt).first()
    if not score:
        raise HTTPException(status_code=404, detail="No health score yet")
    return score


@router.post("/{machine_id}/telemetry", response_model=TelemetryEventPublic)
async def ingest_telemetry(
    machine_id: uuid.UUID,
    payload: TelemetryEventCreate,
    session: SessionDep,
    _user: InternalUser,
) -> Any:
    machine = session.get(Machine, machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    event = TelemetryEvent.model_validate(payload, update={"machine_id": machine_id})
    machine_intelligence.apply_telemetry(session, machine, event)
    await redis.publish(
        redis.TELEMETRY_CHANNEL,
        {"machine_id": str(machine_id), "health_score": machine.health_score},
    )
    return event


@router.post("/{machine_id}/ask", response_model=AskResponse)
async def ask_machine(
    machine_id: uuid.UUID,
    payload: AskRequest,
    session: SessionDep,
    _user: InternalUser,
) -> Any:
    if not session.get(Machine, machine_id):
        raise HTTPException(status_code=404, detail="Machine not found")
    return await askai.answer(session, payload.question, machine_id=machine_id)
