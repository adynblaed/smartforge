import uuid
from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from app.core.crypto import EncryptedString
from app.models.base import created_at_field


class OrderStage(str, Enum):
    received = "received"
    scheduled = "scheduled"
    in_production = "in_production"
    inspection = "inspection"
    complete = "complete"
    shipped = "shipped"


class EscalationStatus(str, Enum):
    open = "open"
    assigned = "assigned"
    resolved = "resolved"


# ---- Customer (account anchor for portal users) ----
class CustomerBase(SQLModel):
    name: str = Field(max_length=255)
    contact_email: str | None = Field(default=None, max_length=255)


class CustomerCreate(CustomerBase):
    pass


class Customer(CustomerBase, table=True):
    __tablename__ = "customer"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class CustomerPublic(CustomerBase):
    id: uuid.UUID
    created_at: datetime | None = None


# ---- Customer orders ----
class CustomerOrderBase(SQLModel):
    customer_id: uuid.UUID = Field(foreign_key="customer.id", index=True)
    order_number: str = Field(max_length=64, index=True)
    part_type: str = Field(max_length=255)
    quantity: int = Field(default=1)
    estimated_completion: datetime | None = Field(default=None)
    delayed: bool = Field(default=False)
    delay_reason: str | None = Field(default=None, max_length=512)


class CustomerOrderCreate(CustomerOrderBase):
    pass


class CustomerOrder(CustomerOrderBase, table=True):
    __tablename__ = "customer_orders"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    stage: OrderStage = Field(default=OrderStage.received, index=True)
    created_at: datetime | None = created_at_field()


# Customer-safe public projection (no internal cost/job linkage exposed).
class CustomerOrderPublic(SQLModel):
    id: uuid.UUID
    order_number: str
    part_type: str
    quantity: int
    stage: OrderStage
    estimated_completion: datetime | None = None
    delayed: bool = False
    delay_reason: str | None = None
    created_at: datetime | None = None


class CustomerOrdersPublic(SQLModel):
    data: list[CustomerOrderPublic]
    count: int


# ---- Customer messages (chatbot transcript) ----
class CustomerMessageBase(SQLModel):
    customer_id: uuid.UUID = Field(foreign_key="customer.id", index=True)
    order_id: uuid.UUID | None = Field(default=None, foreign_key="customer_orders.id")
    # Encrypted at rest (chat transcript).
    question: str = Field(sa_type=EncryptedString)


class CustomerMessage(CustomerMessageBase, table=True):
    __tablename__ = "customer_messages"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    answer: str | None = Field(default=None, sa_type=EncryptedString)
    confidence: float = Field(default=1.0)
    escalated: bool = Field(default=False)
    created_at: datetime | None = created_at_field()


class CustomerMessagePublic(SQLModel):
    id: uuid.UUID
    question: str
    answer: str | None = None
    confidence: float = 1.0
    escalated: bool = False
    created_at: datetime | None = None


# ---- Escalations (AI-to-human handoff) ----
class EscalationBase(SQLModel):
    customer_id: uuid.UUID = Field(foreign_key="customer.id", index=True)
    order_id: uuid.UUID | None = Field(default=None, foreign_key="customer_orders.id")
    question: str = Field(max_length=2048)
    ai_confidence: float = Field(default=0.0)
    reason: str | None = Field(default=None, max_length=512)
    assigned_team: str | None = Field(default=None, max_length=128)


class EscalationCreate(SQLModel):
    order_id: uuid.UUID | None = None
    question: str
    ai_confidence: float = 0.0
    reason: str | None = None


class Escalation(EscalationBase, table=True):
    __tablename__ = "escalations"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: EscalationStatus = Field(default=EscalationStatus.open, index=True)
    # AI/human escalation content encrypted at rest.
    original_ai_answer: str | None = Field(default=None, sa_type=EncryptedString)
    human_response: str | None = Field(default=None, sa_type=EncryptedString)
    created_at: datetime | None = created_at_field()


class EscalationPublic(EscalationBase):
    id: uuid.UUID
    status: EscalationStatus
    original_ai_answer: str | None = None
    human_response: str | None = None
    created_at: datetime | None = None


class EscalationsPublic(SQLModel):
    data: list[EscalationPublic]
    count: int


class HumanResponse(SQLModel):
    human_response: str
    assigned_team: str | None = None
