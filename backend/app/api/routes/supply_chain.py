"""Supply chain, PO, inventory, quoting & job-intake APIs (spec §6, Module 4)."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import desc, select

from app.api.deps import InternalUser, SessionDep
from app.core import llm
from app.models import (
    Customer,
    CustomerOrder,
    InventoryItem,
    InventoryItemPublic,
    InventoryItemsPublic,
    Job,
    JobCreate,
    JobPublic,
    JobsPublic,
    JobStatus,
    MaterialReorder,
    MaterialReorderPublic,
    MaterialReordersPublic,
    PurchaseOrder,
    PurchaseOrdersPublic,
    Quote,
    QuoteCreate,
    QuotePublic,
    QuotesPublic,
    ReorderActionRequest,
    Supplier,
    SuppliersPublic,
)
from app.models.base import get_datetime_utc
from app.models.reorder import REORDER_ACTION_STATUS
from app.services import supply_chain as sc
from app.services.common import list_and_count, write_audit

router = APIRouter(tags=["supply-chain"])


# ---- 4D Inventory & suppliers ----
@router.get("/inventory", response_model=InventoryItemsPublic)
def read_inventory(session: SessionDep, _user: InternalUser) -> Any:
    items = list(session.exec(select(InventoryItem)).all())
    data = []
    for i in items:
        pub = InventoryItemPublic.model_validate(i, from_attributes=True)
        pub.below_threshold = i.quantity < i.reorder_threshold
        data.append(pub)
    return InventoryItemsPublic(data=data, count=len(data))


@router.get("/suppliers", response_model=SuppliersPublic)
def read_suppliers(session: SessionDep, _user: InternalUser) -> Any:
    rows = list(session.exec(select(Supplier)).all())
    return SuppliersPublic(data=rows, count=len(rows))


@router.get("/supply-chain/risks")
def read_risks(session: SessionDep, _user: InternalUser) -> Any:
    low_stock = sc.inventory_below_threshold(session)
    delayed = list(session.exec(
        select(Supplier).where(Supplier.status != "ok")
    ).all())
    return {
        "low_stock_materials": [InventoryItemPublic.model_validate(
            i, from_attributes=True, update={"below_threshold": True}) for i in low_stock],
        "delayed_suppliers": delayed,
        "jobs_at_risk": list(session.exec(
            select(Job).where(Job.status == JobStatus.scheduled)).all()),
        "suggested_reorders": [i.sku for i in low_stock],
    }


# ---- Material reorders (persisted operator decisions) ----
@router.get("/supply-chain/reorders", response_model=MaterialReordersPublic)
def read_reorders(session: SessionDep, _user: InternalUser) -> Any:
    """Every persisted reorder decision (one per SKU). The Supply Chain page
    overlays these onto the derived schedule so approve/adjust/cancel survive a
    reload."""
    rows = list(
        session.exec(
            select(MaterialReorder).order_by(desc(MaterialReorder.created_at))
        ).all()
    )
    return MaterialReordersPublic(data=rows, count=len(rows))


@router.post("/supply-chain/reorders", response_model=MaterialReorderPublic)
def act_on_reorder(
    payload: ReorderActionRequest, session: SessionDep, user: InternalUser
) -> Any:
    """Approve / adjust / cancel a reorder. Upserts by SKU and records the
    signing-off operator + timestamp; audited."""
    status = REORDER_ACTION_STATUS.get(payload.action)
    if not status:
        raise HTTPException(status_code=400, detail=f"Invalid action: {payload.action}")

    row = session.exec(
        select(MaterialReorder).where(MaterialReorder.sku == payload.sku)
    ).first()
    if row is None:
        row = MaterialReorder(sku=payload.sku)

    row.status = status
    row.quantity = payload.quantity
    if payload.reason is not None:
        row.reason = payload.reason
    row.machine_code = payload.machine_code
    row.line = payload.line
    row.scheduled_for = payload.scheduled_for
    row.inventory_item_id = payload.inventory_item_id
    row.signed_off_by = user.full_name or user.email
    row.signed_off_at = get_datetime_utc()

    session.add(row)
    session.commit()
    session.refresh(row)
    write_audit(
        session,
        actor=user,
        action=f"reorder.{payload.action}",
        entity_type="reorder",
        entity_id=row.id,
        detail=payload.sku,
    )
    return row


# ---- 4C Purchase orders ----
@router.get("/purchase-orders", response_model=PurchaseOrdersPublic)
def read_purchase_orders(session: SessionDep, _user: InternalUser) -> Any:
    rows, count = list_and_count(
        session, PurchaseOrder, order_by=desc(PurchaseOrder.created_at)
    )
    return PurchaseOrdersPublic(data=rows, count=count)


@router.get("/order-tracker")
def read_order_tracker(
    session: SessionDep, _user: InternalUser, active_only: bool = True
) -> Any:
    """Denormalized Order Tracker table: every (active) purchase order with its
    customer order, customer, supplier, status and total — the system-of-record
    table view. Also the datasource ForgeAI reads on every chat."""
    suppliers = {s.id: s.name for s in session.exec(select(Supplier)).all()}
    orders = {o.id: o for o in session.exec(select(CustomerOrder)).all()}
    customers = {c.id: c.name for c in session.exec(select(Customer)).all()}
    pos = session.exec(
        select(PurchaseOrder).order_by(desc(PurchaseOrder.created_at))
    ).all()
    data = []
    for p in pos:
        if active_only and p.status.value == "closed":
            continue
        order = orders.get(p.customer_order_id) if p.customer_order_id else None
        cust = customers.get(order.customer_id) if order else None
        data.append(
            {
                "po_number": p.po_number,
                "order_number": order.order_number if order else "—",
                "customer": cust or "—",
                "part_type": order.part_type if order else "—",
                "quantity": order.quantity if order else 0,
                "supplier": suppliers.get(p.supplier_id, "—") if p.supplier_id else "—",
                "status": p.status.value,
                "amount": round(p.amount, 2),
                "shop_floor_ready": p.shop_floor_ready,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
        )
    return {"data": data, "count": len(data)}


# ---- 4B Quoting ----
@router.get("/quotes", response_model=QuotesPublic)
def read_quotes(session: SessionDep, _user: InternalUser) -> Any:
    rows, count = list_and_count(session, Quote, order_by=desc(Quote.created_at))
    return QuotesPublic(data=rows, count=count)


@router.post("/quotes/generate", response_model=QuotePublic)
def generate_quote(
    payload: QuoteCreate, session: SessionDep, user: InternalUser
) -> Any:
    quote = sc.price_quote(Quote.model_validate(payload))
    session.add(quote)
    session.commit()
    session.refresh(quote)
    write_audit(session, actor=user, action="quote.generate",
                entity_type="quote", entity_id=quote.id)
    return quote


# ---- 4A Job intake ----
@router.get("/jobs", response_model=JobsPublic)
def read_jobs(session: SessionDep, _user: InternalUser) -> Any:
    rows, count = list_and_count(session, Job, order_by=desc(Job.created_at))
    return JobsPublic(data=rows, count=count)


@router.post("/jobs", response_model=JobPublic)
def create_job(payload: JobCreate, session: SessionDep, _user: InternalUser) -> Any:
    job = Job.model_validate(payload)
    missing = [f for f in ("part_type", "quantity", "due_date")
               if not getattr(job, f)]
    job.missing_info = ",".join(missing) or None
    job.suggested_priority = job.priority
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


_INTAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "customer": {"type": "string"},
        "part_type": {"type": "string"},
        "quantity": {"type": "integer"},
        "required_materials": {"type": "string"},
        "priority": {"type": "integer"},
        "special_instructions": {"type": "string"},
    },
    "required": ["customer", "part_type", "quantity"],
    "additionalProperties": False,
}


@router.post("/jobs/intake", response_model=JobPublic)
async def intake_job(
    raw_text: str, session: SessionDep, _user: InternalUser
) -> Any:
    """Parse a free-text order into a structured job (Claude-assisted, §4A)."""
    try:
        data = await llm.extract_json(
            system="Extract a manufacturing job request into the schema. "
            "Infer reasonable values; priority 1 (high) to 5 (low).",
            user=raw_text,
            schema=_INTAKE_SCHEMA,
        )
    except llm.LLMUnavailable:
        data = {"customer": "Unknown", "part_type": raw_text[:64], "quantity": 1}
    job = Job(
        customer=data.get("customer", "Unknown"),
        part_type=data.get("part_type", "unspecified"),
        quantity=int(data.get("quantity", 1)),
        required_materials=data.get("required_materials"),
        priority=int(data.get("priority", 3)),
        special_instructions=data.get("special_instructions"),
        status=JobStatus.intake,
    )
    job.suggested_priority = job.priority
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.post("/jobs/{job_id}/approve", response_model=JobPublic)
def approve_job(job_id: uuid.UUID, session: SessionDep, user: InternalUser) -> Any:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = JobStatus.approved
    session.add(job)
    session.commit()
    session.refresh(job)
    write_audit(session, actor=user, action="job.approve",
                entity_type="job", entity_id=job.id)
    return job
