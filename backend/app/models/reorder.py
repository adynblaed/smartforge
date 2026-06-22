"""Material reorders.

Reorders are *derived* from below-threshold inventory, but the operator's
decision on each one — approve / adjust / cancel, the signed-off quantity, the
reason, and who signed off — is a durable, audited record. One row per SKU
holds the current decision (upserted on each action), so the Supply Chain page
can reload the operator's choices instead of losing them on refresh.
"""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import created_at_field

# Allowed reorder states (plain VARCHAR — no native DB enums).
REORDER_STATUSES = ("pending", "approved", "adjusted", "cancelled")
# UI action → persisted status.
REORDER_ACTION_STATUS = {
    "approve": "approved",
    "adjust": "adjusted",
    "cancel": "cancelled",
}


class MaterialReorderBase(SQLModel):
    sku: str = Field(index=True, unique=True, max_length=64)
    inventory_item_id: uuid.UUID | None = Field(
        default=None, foreign_key="inventory_items.id"
    )
    status: str = Field(default="pending", index=True, max_length=24)
    quantity: float = Field(default=0.0)
    reason: str | None = Field(default=None, max_length=1000)
    # Machine / line the material feeds (derived client-side from the SKU).
    machine_code: str | None = Field(default=None, max_length=64)
    line: str | None = Field(default=None, max_length=64)
    scheduled_for: datetime | None = Field(default=None)


class MaterialReorder(MaterialReorderBase, table=True):
    __tablename__ = "material_reorders"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    signed_off_by: str | None = Field(default=None, max_length=255)
    signed_off_at: datetime | None = Field(default=None)
    created_at: datetime | None = created_at_field()


class ReorderActionRequest(SQLModel):
    """Operator action on a single reorder, posted from the Supply Chain page."""

    sku: str
    action: str  # approve | adjust | cancel
    quantity: float = 0.0
    reason: str | None = None
    machine_code: str | None = None
    line: str | None = None
    scheduled_for: datetime | None = None
    inventory_item_id: uuid.UUID | None = None


class MaterialReorderPublic(MaterialReorderBase):
    id: uuid.UUID
    signed_off_by: str | None = None
    signed_off_at: datetime | None = None
    created_at: datetime | None = None


class MaterialReordersPublic(SQLModel):
    data: list[MaterialReorderPublic]
    count: int
