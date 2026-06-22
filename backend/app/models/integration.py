import uuid
from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from app.models.base import created_at_field


class SyncDirection(str, Enum):
    inbound = "inbound"
    outbound = "outbound"


class SyncStatus(str, Enum):
    success = "success"
    failed = "failed"
    pending = "pending"


class _SyncEventBase(SQLModel):
    entity_type: str = Field(max_length=64)  # work_orders, jobs, inventory, ...
    entity_id: str | None = Field(default=None, max_length=128)
    direction: SyncDirection = Field(default=SyncDirection.inbound)
    status: SyncStatus = Field(default=SyncStatus.success, index=True)
    detail: str | None = Field(default=None, max_length=1024)


class ErpSyncEvent(_SyncEventBase, table=True):
    __tablename__ = "erp_sync_events"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class MesSyncEvent(_SyncEventBase, table=True):
    __tablename__ = "mes_sync_events"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class SyncEventPublic(_SyncEventBase):
    id: uuid.UUID
    created_at: datetime | None = None


class SyncEventsPublic(SQLModel):
    data: list[SyncEventPublic]
    count: int


class IntegrationStatus(SQLModel):
    system: str  # "erp" | "mes"
    connected: bool
    last_successful_sync: datetime | None = None
    failed_records: int = 0
    total_events: int = 0


class IntegrationsStatusPublic(SQLModel):
    erp: IntegrationStatus
    mes: IntegrationStatus
