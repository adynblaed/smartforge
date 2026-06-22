import uuid
from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from app.models.base import created_at_field


class SupplierStatus(str, Enum):
    ok = "ok"
    delayed = "delayed"
    at_risk = "at_risk"


class PurchaseOrderStatus(str, Enum):
    draft = "draft"
    open = "open"
    received = "received"
    closed = "closed"


class QuoteStatus(str, Enum):
    draft = "draft"
    sent = "sent"
    approved = "approved"
    rejected = "rejected"


# ---- Suppliers ----
class SupplierBase(SQLModel):
    name: str = Field(max_length=255)
    status: SupplierStatus = Field(default=SupplierStatus.ok)
    lead_time_days: int = Field(default=7)
    contact: str | None = Field(default=None, max_length=255)


class SupplierCreate(SupplierBase):
    pass


class Supplier(SupplierBase, table=True):
    __tablename__ = "suppliers"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class SupplierPublic(SupplierBase):
    id: uuid.UUID
    created_at: datetime | None = None


class SuppliersPublic(SQLModel):
    data: list[SupplierPublic]
    count: int


# ---- Inventory items / raw materials ----
class InventoryItemBase(SQLModel):
    sku: str = Field(max_length=64, index=True)
    name: str = Field(max_length=255)
    material_type: str | None = Field(default=None, max_length=128)
    quantity: float = Field(default=0.0)
    unit: str = Field(default="ea", max_length=16)
    reorder_threshold: float = Field(default=0.0)
    supplier_id: uuid.UUID | None = Field(default=None, foreign_key="suppliers.id")
    factory_id: uuid.UUID | None = Field(default=None, foreign_key="factory.id")


class InventoryItemCreate(InventoryItemBase):
    pass


class InventoryItem(InventoryItemBase, table=True):
    __tablename__ = "inventory_items"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class InventoryItemPublic(InventoryItemBase):
    id: uuid.UUID
    created_at: datetime | None = None
    below_threshold: bool = False


class InventoryItemsPublic(SQLModel):
    data: list[InventoryItemPublic]
    count: int


# ---- Purchase orders ----
class PurchaseOrderBase(SQLModel):
    po_number: str = Field(max_length=64, index=True)
    supplier_id: uuid.UUID | None = Field(default=None, foreign_key="suppliers.id")
    customer_order_id: uuid.UUID | None = Field(
        default=None, foreign_key="customer_orders.id"
    )
    job_id: uuid.UUID | None = Field(default=None, foreign_key="jobs.id")
    inventory_item_id: uuid.UUID | None = Field(
        default=None, foreign_key="inventory_items.id"
    )
    amount: float = Field(default=0.0)


class PurchaseOrderCreate(PurchaseOrderBase):
    pass


class PurchaseOrder(PurchaseOrderBase, table=True):
    __tablename__ = "purchase_orders"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: PurchaseOrderStatus = Field(default=PurchaseOrderStatus.open, index=True)
    shop_floor_ready: bool = Field(default=False)
    created_at: datetime | None = created_at_field()


class PurchaseOrderPublic(PurchaseOrderBase):
    id: uuid.UUID
    status: PurchaseOrderStatus
    shop_floor_ready: bool
    created_at: datetime | None = None


class PurchaseOrdersPublic(SQLModel):
    data: list[PurchaseOrderPublic]
    count: int


# ---- Quotes ----
class QuoteBase(SQLModel):
    customer: str = Field(max_length=255)
    part_type: str = Field(max_length=255)
    quantity: int = Field(default=1)
    material_cost: float = Field(default=0.0)
    labor_cost: float = Field(default=0.0)
    machine_time_cost: float = Field(default=0.0)
    rush_premium: float = Field(default=0.0)
    rush: bool = Field(default=False)


class QuoteCreate(QuoteBase):
    pass


class Quote(QuoteBase, table=True):
    __tablename__ = "quotes"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    estimated_price: float = Field(default=0.0)
    margin_estimate: float = Field(default=0.0)
    timeline_days: int = Field(default=0)
    risk_flags: str | None = Field(default=None, max_length=512)
    status: QuoteStatus = Field(default=QuoteStatus.draft, index=True)
    created_at: datetime | None = created_at_field()


class QuotePublic(QuoteBase):
    id: uuid.UUID
    estimated_price: float
    margin_estimate: float
    timeline_days: int
    risk_flags: str | None = None
    status: QuoteStatus
    created_at: datetime | None = None


class QuotesPublic(SQLModel):
    data: list[QuotePublic]
    count: int
