"""Maintenance ticketing APIs.

The Maintenance Alert Center as a bonafide ticketing system: serialized tickets
(``TICKET-NNNN``) carrying audience-aware explanations, an acknowledgement +
note trail (with user email, timestamp and timezone), the parts required for the
repair tied to live inventory + supplier lead times, and a deep-link into the
relevant SOP chapter. Tickets and SOPs/KB docs are @-referenceable by code.
"""

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import col, desc, func, select

from app.api.deps import InternalUser, SessionDep
from app.models import (
    Alert,
    AlertStatus,
    Incident,
    InventoryItem,
    KnowledgeDocument,
    Machine,
    MaintenanceTicket,
    MaintenanceTicketDetail,
    MaintenanceTicketLog,
    MaintenanceTicketPart,
    MaintenanceTicketPublic,
    MaintenanceTicketsPublic,
    Sop,
    Supplier,
    TicketAcknowledge,
    TicketLogPublic,
    TicketNote,
    TicketPartPublic,
    TicketReference,
    TicketStatusUpdate,
)
from app.models.base import get_datetime_utc
from app.models.maintenance_ticket import TICKET_STATUSES
from app.services.common import list_and_count, write_audit

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _machine_codes(session: SessionDep) -> dict[uuid.UUID, str]:
    return {m.id: m.code for m in session.exec(select(Machine)).all()}


def _ticket_detail(
    ticket: MaintenanceTicket, session: SessionDep
) -> MaintenanceTicketDetail:
    machine = session.get(Machine, ticket.machine_id) if ticket.machine_id else None
    sop = session.get(Sop, ticket.sop_id) if ticket.sop_id else None
    incident = session.get(Incident, ticket.incident_id) if ticket.incident_id else None

    # Parts required, tied to live inventory + supplier lead times. We back-date
    # the order-by from when the maintenance is due so it arrives in time.
    needed_by = (ticket.created_at or get_datetime_utc()) + timedelta(
        days=ticket.suggested_window_days
    )
    parts: list[TicketPartPublic] = []
    part_rows = session.exec(
        select(MaintenanceTicketPart).where(
            MaintenanceTicketPart.ticket_id == ticket.id
        )
    ).all()
    for p in part_rows:
        inv = (
            session.get(InventoryItem, p.inventory_item_id)
            if p.inventory_item_id
            else None
        )
        sup = (
            session.get(Supplier, inv.supplier_id) if inv and inv.supplier_id else None
        )
        on_hand = inv.quantity if inv else 0.0
        lead = sup.lead_time_days if sup else 0
        parts.append(
            TicketPartPublic(
                id=p.id,
                name=p.name,
                qty_needed=p.qty_needed,
                inventory_item_id=p.inventory_item_id,
                sku=inv.sku if inv else None,
                on_hand=on_hand,
                unit=inv.unit if inv else "ea",
                lead_time_days=lead,
                supplier_name=sup.name if sup else None,
                supplier_status=sup.status.value if sup else None,
                needed_by=needed_by,
                order_by=needed_by - timedelta(days=lead),
                in_stock=on_hand >= p.qty_needed,
                shortfall=max(0.0, p.qty_needed - on_hand),
            )
        )

    log_rows = session.exec(
        select(MaintenanceTicketLog)
        .where(MaintenanceTicketLog.ticket_id == ticket.id)
        .order_by(col(MaintenanceTicketLog.created_at))
    ).all()
    logs = [TicketLogPublic(**log.model_dump()) for log in log_rows]

    return MaintenanceTicketDetail(
        **ticket.model_dump(),
        machine_code=machine.code if machine else None,
        machine_name=machine.name if machine else None,
        sop_code=sop.code if sop else None,
        incident_title=incident.title if incident else None,
        parts=parts,
        logs=logs,
    )


@router.get("/", response_model=MaintenanceTicketsPublic)
def read_tickets(
    session: SessionDep,
    _user: InternalUser,
    skip: int = 0,
    limit: int = 200,
    status: str | None = None,
) -> Any:
    where = (MaintenanceTicket.status == status) if status else None
    rows, count = list_and_count(
        session,
        MaintenanceTicket,
        skip=skip,
        limit=limit,
        where=where,
        order_by=desc(MaintenanceTicket.created_at),
    )
    codes = _machine_codes(session)
    data = [
        MaintenanceTicketPublic(**t.model_dump(), machine_code=codes.get(t.machine_id))
        for t in rows
    ]
    return MaintenanceTicketsPublic(data=data, count=count)


def _next_ticket_code(session: SessionDep) -> str:
    n = session.exec(select(func.count()).select_from(MaintenanceTicket)).one()
    return f"TICKET-{int(n) + 1:04d}"


@router.post("/from-incident/{incident_id}", response_model=MaintenanceTicketDetail)
def ticket_from_incident(
    incident_id: uuid.UUID, session: SessionDep, user: InternalUser
) -> Any:
    """Create-or-get the maintenance ticket for an incident (every open incident
    is trackable as a ticket)."""
    incident = session.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    existing = session.exec(
        select(MaintenanceTicket).where(MaintenanceTicket.incident_id == incident_id)
    ).first()
    if existing:
        return _ticket_detail(existing, session)

    machine = None
    if incident.affected_machines:
        first = incident.affected_machines.split(",")[0].strip()
        try:
            machine = session.get(Machine, uuid.UUID(first))
        except ValueError:
            machine = None
    sop = (
        session.exec(select(Sop).where(Sop.machine_id == machine.id)).first()
        if machine
        else None
    )
    sev = getattr(incident.severity, "value", str(incident.severity))
    ticket = MaintenanceTicket(
        code=_next_ticket_code(session),
        title=incident.title,
        machine_id=machine.id if machine else None,
        incident_id=incident.id,
        severity=sev,
        status="open",
        what_happened=(
            f"An incident was logged — “{incident.title}”. It needs maintenance "
            "attention to restore normal operation."
        ),
        executive_summary=(
            f"Incident impact: ~{incident.downtime_minutes} min downtime, "
            f"{incident.delayed_orders} delayed order(s), est. "
            f"${incident.estimated_cost:,.0f}. Resolve promptly to limit exposure."
        ),
        operator_detail=(
            f"Linked to incident “{incident.title}”. Review the RCA, address the root "
            "cause, and confirm the line is restored."
            + (f" Affected machine: {machine.code}." if machine else "")
        ),
        remediation=(
            "Follow the incident RCA corrective actions and the machine SOP."
            + (f" See @{sop.code}." if sop else "")
        ),
        sop_id=sop.id if sop else None,
        suggested_window_days=1 if sev in ("high", "critical") else 3,
    )
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    session.add(
        MaintenanceTicketLog(
            ticket_id=ticket.id,
            kind="system",
            message=f"Ticket opened from incident “{incident.title}”.",
        )
    )
    session.commit()
    write_audit(
        session,
        actor=user,
        action="ticket.from_incident",
        entity_type="maintenance_ticket",
        entity_id=ticket.id,
    )
    return _ticket_detail(ticket, session)


@router.post("/from-alert/{alert_id}", response_model=MaintenanceTicketDetail)
def ticket_from_alert(
    alert_id: uuid.UUID, session: SessionDep, user: InternalUser
) -> Any:
    """Generate a full, serialized maintenance ticket from an alert (and
    acknowledge the alert so it leaves the active queue)."""
    alert = session.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    existing = session.exec(
        select(MaintenanceTicket).where(MaintenanceTicket.alert_id == alert_id)
    ).first()
    if existing:
        return _ticket_detail(existing, session)

    machine = session.get(Machine, alert.machine_id) if alert.machine_id else None
    sop = (
        session.exec(select(Sop).where(Sop.machine_id == machine.id)).first()
        if machine
        else None
    )
    sev = getattr(alert.severity, "value", str(alert.severity))
    code = machine.code if machine else "machine"
    ticket = MaintenanceTicket(
        code=_next_ticket_code(session),
        title=f"{code}: {alert.message}",
        machine_id=alert.machine_id,
        alert_id=alert.id,
        severity=sev,
        status="open",
        what_happened=(
            f"An alert fired on {code}: {alert.message}. It needs maintenance "
            "attention before it escalates."
        ),
        executive_summary=(
            f"{sev.title()}-severity alert on {code} (rule: {alert.rule}). Actioning "
            "now avoids unplanned downtime and scrap."
        ),
        operator_detail=(
            f"Rule '{alert.rule}' triggered: {alert.message}."
            + (
                f" Recommended: {alert.recommended_action}"
                if alert.recommended_action
                else ""
            )
            + (
                f" Suggested window: {alert.suggested_window}."
                if alert.suggested_window
                else ""
            )
        ),
        remediation=(
            (alert.recommended_action or "Inspect and service per SOP.")
            + (f" See @{sop.code}." if sop else "")
        ),
        sop_id=sop.id if sop else None,
        suggested_window_days=1 if sev in ("high", "critical") else 3,
    )
    session.add(ticket)
    # Acknowledge the alert — it's now tracked as a ticket.
    alert.status = AlertStatus.acknowledged
    alert.acknowledged_at = get_datetime_utc()
    session.add(alert)
    session.commit()
    session.refresh(ticket)
    session.add(
        MaintenanceTicketLog(
            ticket_id=ticket.id,
            kind="system",
            message=f"Ticket auto-generated from alert: {alert.rule}.",
        )
    )
    session.commit()
    write_audit(
        session,
        actor=user,
        action="ticket.from_alert",
        entity_type="maintenance_ticket",
        entity_id=ticket.id,
    )
    return _ticket_detail(ticket, session)


@router.get("/by-incident", response_model=dict[str, str])
def tickets_by_incident(session: SessionDep, _user: InternalUser) -> Any:
    """Map of incident_id → ticket code, for surfacing the link in the UI."""
    rows = session.exec(
        select(MaintenanceTicket).where(MaintenanceTicket.incident_id.is_not(None))  # type: ignore[union-attr]
    ).all()
    return {str(t.incident_id): t.code for t in rows}


@router.get("/references", response_model=list[TicketReference])
def read_references(session: SessionDep, _user: InternalUser) -> Any:
    """Everything @-referenceable from a ticket note: tickets, SOPs, KB docs."""
    refs: list[TicketReference] = []
    for t in session.exec(
        select(MaintenanceTicket).order_by(MaintenanceTicket.code)
    ).all():
        refs.append(TicketReference(code=t.code, kind="ticket", id=t.id, title=t.title))
    for s in session.exec(select(Sop).order_by(Sop.code)).all():
        refs.append(TicketReference(code=s.code, kind="sop", id=s.id, title=s.title))
    for k in session.exec(select(KnowledgeDocument)).all():
        refs.append(
            TicketReference(
                code=f"KB-{str(k.id)[:8].upper()}", kind="kb", id=k.id, title=k.title
            )
        )
    return refs


@router.get("/{ticket_id}", response_model=MaintenanceTicketDetail)
def read_ticket(ticket_id: uuid.UUID, session: SessionDep, _user: InternalUser) -> Any:
    ticket = session.get(MaintenanceTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return _ticket_detail(ticket, session)


@router.post("/{ticket_id}/acknowledge", response_model=MaintenanceTicketDetail)
def acknowledge_ticket(
    ticket_id: uuid.UUID,
    body: TicketAcknowledge,
    session: SessionDep,
    user: InternalUser,
) -> Any:
    ticket = session.get(MaintenanceTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    now = get_datetime_utc()
    if ticket.status == "open":
        ticket.status = "acknowledged"
    ticket.acknowledged_by = user.email
    ticket.acknowledged_at = now
    ticket.acknowledged_tz = body.tz
    session.add(ticket)
    session.add(
        MaintenanceTicketLog(
            ticket_id=ticket.id,
            kind="acknowledgement",
            author_email=user.email,
            message=f"Acknowledged by {user.email}",
            tz=body.tz,
        )
    )
    if body.note and body.note.strip():
        session.add(
            MaintenanceTicketLog(
                ticket_id=ticket.id,
                kind="note",
                author_email=user.email,
                message=body.note.strip(),
                tz=body.tz,
            )
        )
    session.commit()
    write_audit(
        session,
        actor=user,
        action="ticket.acknowledge",
        entity_type="maintenance_ticket",
        entity_id=ticket.id,
    )
    session.refresh(ticket)
    return _ticket_detail(ticket, session)


@router.post("/{ticket_id}/notes", response_model=MaintenanceTicketDetail)
def add_note(
    ticket_id: uuid.UUID, body: TicketNote, session: SessionDep, user: InternalUser
) -> Any:
    ticket = session.get(MaintenanceTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="Empty note")
    session.add(
        MaintenanceTicketLog(
            ticket_id=ticket.id,
            kind="note",
            author_email=user.email,
            message=body.message.strip(),
            tz=body.tz,
        )
    )
    session.commit()
    write_audit(
        session,
        actor=user,
        action="ticket.note",
        entity_type="maintenance_ticket",
        entity_id=ticket.id,
    )
    return _ticket_detail(ticket, session)


@router.post("/{ticket_id}/status", response_model=MaintenanceTicketDetail)
def update_status(
    ticket_id: uuid.UUID,
    body: TicketStatusUpdate,
    session: SessionDep,
    user: InternalUser,
) -> Any:
    ticket = session.get(MaintenanceTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if body.status not in TICKET_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    old = ticket.status
    ticket.status = body.status
    session.add(ticket)
    session.add(
        MaintenanceTicketLog(
            ticket_id=ticket.id,
            kind="status_change",
            author_email=user.email,
            message=f"Status changed {old} → {body.status}",
        )
    )
    session.commit()
    write_audit(
        session,
        actor=user,
        action="ticket.status",
        entity_type="maintenance_ticket",
        entity_id=ticket.id,
        detail=body.status,
    )
    session.refresh(ticket)
    return _ticket_detail(ticket, session)
