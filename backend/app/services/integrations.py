"""ERP/MES sync adapters + Fiix work-order adapter (mocked) — Module 1D & 3A."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import cast

from sqlmodel import Session, desc, func, select

from app.models import (
    ErpSyncEvent,
    FiixSyncState,
    IntegrationsStatusPublic,
    IntegrationStatus,
    MesSyncEvent,
    SyncDirection,
    SyncStatus,
    WorkOrder,
)
from app.models.base import get_datetime_utc

ERP_ENTITIES = [
    "work_orders",
    "jobs",
    "inventory",
    "production_runs",
    "purchase_orders",
]
MES_ENTITIES = ["machine_states", "production_runs", "jobs"]


def run_sync(session: Session, system: str) -> list[ErpSyncEvent | MesSyncEvent]:
    """Mock a bidirectional sync pass, recording one event per entity type."""
    model = ErpSyncEvent if system == "erp" else MesSyncEvent
    entities = ERP_ENTITIES if system == "erp" else MES_ENTITIES
    events: list[ErpSyncEvent | MesSyncEvent] = []
    for i, entity in enumerate(entities):
        # Deterministically fail one record to exercise the failure UI.
        status = SyncStatus.failed if (i == len(entities) - 1) else SyncStatus.success
        ev = model(
            entity_type=entity,
            entity_id=str(uuid.uuid4()),
            direction=SyncDirection.inbound if i % 2 == 0 else SyncDirection.outbound,
            status=status,
            detail=None if status == SyncStatus.success else "Mock validation error",
        )
        session.add(ev)
        events.append(ev)
    session.commit()
    for ev in events:
        session.refresh(ev)
    return events


def _status_for(
    session: Session, model: type[ErpSyncEvent] | type[MesSyncEvent]
) -> IntegrationStatus:
    total = session.exec(select(func.count()).select_from(model)).one()
    failed = session.exec(
        select(func.count()).select_from(model).where(model.status == SyncStatus.failed)
    ).one()
    # select(model) joins the union to the shared base, so restore the
    # concrete row type (both concrete models carry created_at).
    last_ok = cast(
        "ErpSyncEvent | MesSyncEvent | None",
        session.exec(
            select(model)
            .where(model.status == SyncStatus.success)
            .order_by(desc(model.created_at))
        ).first(),
    )
    return IntegrationStatus(
        system="erp" if model is ErpSyncEvent else "mes",
        connected=True,
        last_successful_sync=last_ok.created_at if last_ok else None,
        failed_records=failed,
        total_events=total,
    )


def integration_status(session: Session) -> IntegrationsStatusPublic:
    return IntegrationsStatusPublic(
        erp=_status_for(session, ErpSyncEvent),
        mes=_status_for(session, MesSyncEvent),
    )


def sync_fiix(session: Session, work_order: WorkOrder) -> WorkOrder:
    """Mock Fiix CMMS push: assigns a Fiix id and marks synced."""
    work_order.fiix_sync_state = FiixSyncState.synced
    work_order.fiix_id = f"FIIX-{str(work_order.id)[:8].upper()}"
    session.add(work_order)
    session.commit()
    session.refresh(work_order)
    return work_order


def now() -> datetime:
    return get_datetime_utc()
