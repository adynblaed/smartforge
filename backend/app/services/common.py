"""Shared service helpers: audit logging + list/count pagination."""

from __future__ import annotations

import uuid
from typing import Any

from sqlmodel import Session, func, select

from app.models import AuditLog, User


def write_audit(
    session: Session,
    *,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID | None = None,
    detail: str | None = None,
) -> None:
    """Append an audit entry (work orders, AI answers, escalations, config changes)."""
    log = AuditLog(
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        detail=detail,
    )
    session.add(log)
    session.commit()


def list_and_count(
    session: Session,
    model: type,
    *,
    skip: int = 0,
    limit: int = 100,
    where: Any | None = None,
    order_by: Any | None = None,
) -> tuple[list[Any], int]:
    """Return (rows, total_count) for a model with optional filter + ordering."""
    count_stmt = select(func.count()).select_from(model)
    data_stmt = select(model)
    if where is not None:
        count_stmt = count_stmt.where(where)
        data_stmt = data_stmt.where(where)
    if order_by is not None:
        data_stmt = data_stmt.order_by(order_by)
    count = session.exec(count_stmt).one()
    rows = session.exec(data_stmt.offset(skip).limit(limit)).all()
    return list(rows), count
