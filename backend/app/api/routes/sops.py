"""Standard Operating Procedure (SOP) APIs.

SOPs are strict, chaptered operating guidelines for factory entities. The detail
endpoint returns ordered sections so the UI can deep-link to a specific chapter.
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import ColumnElement, and_
from sqlmodel import col, select

from app.api.deps import InternalUser, SessionDep
from app.models import (
    Machine,
    Sop,
    SopDetailPublic,
    SopSection,
    SopSectionPublic,
    SopsPublic,
    SopUpdate,
)
from app.services.common import list_and_count, write_audit

router = APIRouter(prefix="/sops", tags=["sops"])


def _resolve_sop(ref: str, session: SessionDep) -> Sop:
    sop: Sop | None = None
    try:
        sop = session.get(Sop, uuid.UUID(ref))
    except ValueError:
        sop = session.exec(select(Sop).where(Sop.code == ref)).first()
    if not sop:
        raise HTTPException(status_code=404, detail="SOP not found")
    return sop


def _sop_detail(sop: Sop, session: SessionDep) -> SopDetailPublic:
    sections = session.exec(
        select(SopSection)
        .where(SopSection.sop_id == sop.id)
        .order_by(col(SopSection.order_index))
    ).all()
    machine_code = None
    if sop.machine_id:
        machine = session.get(Machine, sop.machine_id)
        machine_code = machine.code if machine else None
    return SopDetailPublic(
        **sop.model_dump(),
        machine_code=machine_code,
        sections=[SopSectionPublic(**s.model_dump()) for s in sections],
    )


@router.get("/", response_model=SopsPublic)
def read_sops(
    session: SessionDep,
    _user: InternalUser,
    skip: int = 0,
    limit: int = 200,
    category: str | None = None,
    machine: str | None = None,
) -> Any:
    """List SOPs, optionally filtered by category or by machine code (e.g.
    ``?machine=cnc-01``) so other pages can deep-link a machine's procedures."""
    clauses: list[ColumnElement[bool]] = []
    if category:
        clauses.append(col(Sop.category) == category)
    if machine:
        m = session.exec(select(Machine).where(Machine.code == machine)).first()
        # Unknown machine code → empty result rather than the full list.
        clauses.append(col(Sop.machine_id) == (m.id if m else None))
    where = and_(*clauses) if clauses else None
    rows, count = list_and_count(
        session, Sop, skip=skip, limit=limit, where=where, order_by=Sop.code
    )
    return SopsPublic(data=rows, count=count)


@router.get("/{ref}", response_model=SopDetailPublic)
def read_sop(ref: str, session: SessionDep, _user: InternalUser) -> Any:
    """Look up an SOP by UUID or by its human-readable code (e.g. SOP-PRESS-001)."""
    return _sop_detail(_resolve_sop(ref, session), session)


@router.patch("/{ref}", response_model=SopDetailPublic)
def update_sop(
    ref: str, payload: SopUpdate, session: SessionDep, user: InternalUser
) -> Any:
    """In-place edit of an SOP — title/summary + section title/body (WYSIWYG)."""
    sop = _resolve_sop(ref, session)
    if payload.title is not None:
        sop.title = payload.title
    if payload.summary is not None:
        sop.summary = payload.summary
    session.add(sop)
    for su in payload.sections:
        sec = session.exec(
            select(SopSection).where(
                SopSection.sop_id == sop.id, SopSection.anchor == su.anchor
            )
        ).first()
        if not sec:
            continue
        if su.title is not None:
            sec.title = su.title
        if su.body is not None:
            sec.body = su.body
        session.add(sec)
    session.commit()
    session.refresh(sop)
    write_audit(
        session,
        actor=user,
        action="sop.update",
        entity_type="sop",
        entity_id=str(sop.id),
        detail=sop.code,
    )
    return _sop_detail(sop, session)
