"""Customer portal APIs — customer-scoped, customer-safe (spec §6, Module 5)."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import desc, select

from app.api.deps import CustomerUser, InternalUser, SessionDep
from app.core.config import settings
from app.models import (
    AskRequest,
    AskResponse,
    CustomerMessage,
    CustomerOrder,
    CustomerOrderPublic,
    CustomerOrdersPublic,
    Escalation,
    EscalationCreate,
    EscalationPublic,
    EscalationsPublic,
    EscalationStatus,
    HumanResponse,
)
from app.services import askai
from app.services.common import write_audit

router = APIRouter(prefix="/customer", tags=["customer"])

# Answers below this confidence are auto-escalated (env-overridable).
CONFIDENCE_ESCALATION_THRESHOLD = settings.ESCALATION_CONFIDENCE_THRESHOLD


@router.get("/orders", response_model=CustomerOrdersPublic)
def my_orders(session: SessionDep, user: CustomerUser) -> Any:
    rows = list(
        session.exec(
            select(CustomerOrder)
            .where(CustomerOrder.customer_id == user.customer_id)
            .order_by(desc(CustomerOrder.created_at))
        ).all()
    )
    return CustomerOrdersPublic(data=list(rows), count=len(rows))


@router.get("/orders/{order_id}", response_model=CustomerOrderPublic)
def my_order(order_id: uuid.UUID, session: SessionDep, user: CustomerUser) -> Any:
    order = session.get(CustomerOrder, order_id)
    if not order or order.customer_id != user.customer_id:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/ask", response_model=AskResponse)
async def customer_ask(
    payload: AskRequest, session: SessionDep, user: CustomerUser
) -> Any:
    # Build a customer-safe context from this customer's own orders only.
    orders = list(
        session.exec(
            select(CustomerOrder).where(CustomerOrder.customer_id == user.customer_id)
        ).all()
    )
    order_ctx = "\n".join(
        f"Order {o.order_number}: {o.part_type} x{o.quantity}, stage {o.stage.value}, "
        f"ETA {o.estimated_completion}, delayed={o.delayed}"
        for o in orders
    )
    question = f"{payload.question}\n\n[Customer orders]\n{order_ctx}"
    resp = await askai.answer(session, question, customer_safe=True)
    msg = CustomerMessage(
        customer_id=user.customer_id,
        question=payload.question,
        answer=resp.answer,
        confidence=resp.confidence,
        escalated=resp.confidence < CONFIDENCE_ESCALATION_THRESHOLD,
    )
    session.add(msg)
    session.commit()
    # Privacy: never persist the raw question text in the audit trail.
    write_audit(
        session,
        actor=user,
        action="customer.ask",
        entity_type="customer_message",
        entity_id=msg.id,
    )
    return resp


@router.post("/escalate", response_model=EscalationPublic)
def escalate(payload: EscalationCreate, session: SessionDep, user: CustomerUser) -> Any:
    # Prevent IDOR: a customer may only escalate against their OWN order.
    if payload.order_id is not None:
        order = session.get(CustomerOrder, payload.order_id)
        if not order or order.customer_id != user.customer_id:
            raise HTTPException(status_code=404, detail="Order not found")
    esc = Escalation(
        customer_id=user.customer_id,
        order_id=payload.order_id,
        question=payload.question,
        ai_confidence=payload.ai_confidence,
        reason=payload.reason or "Customer requested human support",
        assigned_team="customer_success",
    )
    session.add(esc)
    session.commit()
    session.refresh(esc)
    write_audit(
        session,
        actor=user,
        action="customer.escalate",
        entity_type="escalation",
        entity_id=esc.id,
    )
    return esc


# ---- Internal side of escalations (5E) ----
@router.get("/escalations", response_model=EscalationsPublic)
def list_escalations(session: SessionDep, _user: InternalUser) -> Any:
    rows = list(
        session.exec(select(Escalation).order_by(desc(Escalation.created_at))).all()
    )
    return EscalationsPublic(data=list(rows), count=len(rows))


@router.post("/escalations/{escalation_id}/respond", response_model=EscalationPublic)
def respond_escalation(
    escalation_id: uuid.UUID,
    payload: HumanResponse,
    session: SessionDep,
    user: InternalUser,
) -> Any:
    esc = session.get(Escalation, escalation_id)
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")
    esc.human_response = payload.human_response
    esc.assigned_team = payload.assigned_team or esc.assigned_team
    esc.status = EscalationStatus.resolved
    session.add(esc)
    session.commit()
    session.refresh(esc)
    write_audit(
        session,
        actor=user,
        action="escalation.respond",
        entity_type="escalation",
        entity_id=esc.id,
    )
    return esc
