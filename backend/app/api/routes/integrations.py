"""ERP/MES integration APIs (spec §6 ERP/MES APIs, Module 3A)."""

from typing import Any

from fastapi import APIRouter
from sqlmodel import desc, select

from app.api.deps import InternalUser, SessionDep
from app.models import (
    ErpSyncEvent,
    IntegrationsStatusPublic,
    MesSyncEvent,
    SyncEventsPublic,
)
from app.services import integrations
from app.services.common import write_audit

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/status", response_model=IntegrationsStatusPublic)
def status(session: SessionDep, _user: InternalUser) -> Any:
    return integrations.integration_status(session)


@router.get("/events", response_model=SyncEventsPublic)
def events(session: SessionDep, _user: InternalUser, system: str = "erp") -> Any:
    model = ErpSyncEvent if system == "erp" else MesSyncEvent
    rows = list(
        session.exec(select(model).order_by(desc(model.created_at)).limit(100)).all()
    )
    return SyncEventsPublic(data=rows, count=len(rows))


@router.post("/erp/sync", response_model=SyncEventsPublic)
def sync_erp(session: SessionDep, user: InternalUser) -> Any:
    rows = integrations.run_sync(session, "erp")
    write_audit(session, actor=user, action="integration.erp_sync", entity_type="erp")
    return SyncEventsPublic(data=rows, count=len(rows))


@router.post("/mes/sync", response_model=SyncEventsPublic)
def sync_mes(session: SessionDep, user: InternalUser) -> Any:
    rows = integrations.run_sync(session, "mes")
    write_audit(session, actor=user, action="integration.mes_sync", entity_type="mes")
    return SyncEventsPublic(data=rows, count=len(rows))
