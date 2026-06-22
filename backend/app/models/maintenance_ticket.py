"""Maintenance ticketing system.

A first-class, serialized ticket (``TICKET-NNNN``) that elevates a maintenance
alert / incident into a tracked work item with:
  * audience-aware logs (layman / executive / operator explanations + remediation),
  * an acknowledgement trail (who, when, in which timezone) and free-form notes,
  * the parts required for the repair, tied to live inventory + supplier lead times,
  * a deep-link into the relevant SOP chapter.

Tickets are interoperable with the rest of the schema via FKs (machine, alert,
incident, sop, inventory items) and a stable human-readable ``code`` so they can be
@-referenced from notes and knowledge bases as ``@TICKET-NNNN``.
"""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import created_at_field

# Allowed string values (plain VARCHAR columns — no native DB enums).
TICKET_STATUSES = ("open", "acknowledged", "in_progress", "resolved", "closed")
TICKET_LOG_KINDS = ("system", "acknowledgement", "note", "status_change")


class MaintenanceTicketBase(SQLModel):
    code: str = Field(index=True, unique=True, max_length=64)  # e.g. "TICKET-0001"
    title: str = Field(max_length=255)
    machine_id: uuid.UUID | None = Field(default=None, foreign_key="machine.id", index=True)
    alert_id: uuid.UUID | None = Field(default=None, foreign_key="alerts.id")
    incident_id: uuid.UUID | None = Field(default=None, foreign_key="incidents.id")
    severity: str = Field(default="medium", max_length=16)
    status: str = Field(default="open", index=True, max_length=24)
    # Audience-aware explanation of what went wrong + how to fix it.
    what_happened: str = Field(default="", max_length=2000)      # layman
    executive_summary: str = Field(default="", max_length=2000)  # executive / business
    operator_detail: str = Field(default="", max_length=2000)    # operator / technical
    remediation: str = Field(default="", max_length=2000)
    sop_id: uuid.UUID | None = Field(default=None, foreign_key="sops.id")
    sop_anchor: str | None = Field(default=None, max_length=64)
    suggested_window_days: int = Field(default=3)  # days until maintenance is due


class MaintenanceTicket(MaintenanceTicketBase, table=True):
    __tablename__ = "maintenance_tickets"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    acknowledged_by: str | None = Field(default=None, max_length=255)
    acknowledged_at: datetime | None = Field(default=None)
    acknowledged_tz: str | None = Field(default=None, max_length=64)
    created_at: datetime | None = created_at_field()


class MaintenanceTicketLogBase(SQLModel):
    ticket_id: uuid.UUID = Field(foreign_key="maintenance_tickets.id", index=True)
    kind: str = Field(default="note", max_length=24)
    author_email: str | None = Field(default=None, max_length=255)
    message: str = Field(default="", max_length=2000)
    tz: str | None = Field(default=None, max_length=64)


class MaintenanceTicketLog(MaintenanceTicketLogBase, table=True):
    __tablename__ = "maintenance_ticket_logs"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class MaintenanceTicketPartBase(SQLModel):
    ticket_id: uuid.UUID = Field(foreign_key="maintenance_tickets.id", index=True)
    inventory_item_id: uuid.UUID | None = Field(
        default=None, foreign_key="inventory_items.id"
    )
    name: str = Field(max_length=255)
    qty_needed: float = Field(default=1.0)


class MaintenanceTicketPart(MaintenanceTicketPartBase, table=True):
    __tablename__ = "maintenance_ticket_parts"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


# ---- Public / response schemas ----
class MaintenanceTicketPublic(MaintenanceTicketBase):
    id: uuid.UUID
    machine_code: str | None = None
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    acknowledged_tz: str | None = None
    created_at: datetime | None = None


class MaintenanceTicketsPublic(SQLModel):
    data: list[MaintenanceTicketPublic]
    count: int


class TicketPartPublic(SQLModel):
    id: uuid.UUID
    name: str
    qty_needed: float
    inventory_item_id: uuid.UUID | None = None
    sku: str | None = None
    on_hand: float = 0.0
    unit: str = "ea"
    lead_time_days: int = 0
    supplier_name: str | None = None
    supplier_status: str | None = None
    needed_by: datetime | None = None
    order_by: datetime | None = None
    in_stock: bool = True
    shortfall: float = 0.0


class TicketLogPublic(SQLModel):
    id: uuid.UUID
    kind: str
    author_email: str | None = None
    message: str
    tz: str | None = None
    created_at: datetime | None = None


class MaintenanceTicketDetail(MaintenanceTicketPublic):
    machine_name: str | None = None
    sop_code: str | None = None
    incident_title: str | None = None
    parts: list[TicketPartPublic] = []
    logs: list[TicketLogPublic] = []


# ---- Request bodies ----
class TicketAcknowledge(SQLModel):
    note: str | None = None
    tz: str | None = None


class TicketNote(SQLModel):
    message: str
    tz: str | None = None


class TicketStatusUpdate(SQLModel):
    status: str


class TicketReference(SQLModel):
    code: str
    kind: str  # ticket | sop | kb
    id: uuid.UUID
    title: str
