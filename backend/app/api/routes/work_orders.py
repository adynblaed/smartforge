"""Work order APIs with Fiix sync (spec §6 Work Order APIs, Module 1D)."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import desc

from app.api.deps import InternalUser, SessionDep
from app.models import (
    Alert,
    WorkOrder,
    WorkOrderCreate,
    WorkOrderPublic,
    WorkOrdersPublic,
    WorkOrderStatus,
)
from app.services import integrations, machine_intelligence
from app.services.common import list_and_count, write_audit

router = APIRouter(prefix="/work-orders", tags=["work-orders"])


@router.get("/", response_model=WorkOrdersPublic)
def read_work_orders(
    session: SessionDep, _user: InternalUser, skip: int = 0, limit: int = 100
) -> Any:
    rows, count = list_and_count(
        session, WorkOrder, skip=skip, limit=limit, order_by=desc(WorkOrder.created_at)
    )
    return WorkOrdersPublic(data=rows, count=count)


@router.post("/", response_model=WorkOrderPublic)
def create_work_order(
    payload: WorkOrderCreate, session: SessionDep, user: InternalUser
) -> Any:
    wo = WorkOrder.model_validate(payload)
    session.add(wo)
    session.commit()
    session.refresh(wo)
    write_audit(session, actor=user, action="work_order.create",
                entity_type="work_order", entity_id=wo.id)
    return wo


@router.post("/from-alert/{alert_id}", response_model=WorkOrderPublic)
def create_from_alert(
    alert_id: uuid.UUID, session: SessionDep, user: InternalUser
) -> Any:
    alert = session.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    wo = machine_intelligence.draft_work_order_from_alert(session, alert)
    write_audit(session, actor=user, action="work_order.draft_from_alert",
                entity_type="work_order", entity_id=wo.id, detail=alert.rule)
    return wo


@router.post("/{wo_id}/approve", response_model=WorkOrderPublic)
def approve_work_order(
    wo_id: uuid.UUID, session: SessionDep, user: InternalUser, approve: bool = True
) -> Any:
    wo = session.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    wo.status = WorkOrderStatus.approved if approve else WorkOrderStatus.rejected
    session.add(wo)
    session.commit()
    session.refresh(wo)
    write_audit(session, actor=user, action=f"work_order.{wo.status.value}",
                entity_type="work_order", entity_id=wo.id)
    return wo


@router.post("/{wo_id}/sync-fiix", response_model=WorkOrderPublic)
def sync_fiix(wo_id: uuid.UUID, session: SessionDep, user: InternalUser) -> Any:
    wo = session.get(WorkOrder, wo_id)
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    wo = integrations.sync_fiix(session, wo)
    write_audit(session, actor=user, action="work_order.sync_fiix",
                entity_type="work_order", entity_id=wo.id, detail=wo.fiix_id)
    return wo
