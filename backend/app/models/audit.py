import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import created_at_field


# ---- Audit log (work orders, AI answers, escalations, config changes) ----
class AuditLogBase(SQLModel):
    actor_id: uuid.UUID | None = Field(default=None, foreign_key="user.id")
    actor_email: str | None = Field(default=None, max_length=255)
    action: str = Field(max_length=128, index=True)  # e.g. "work_order.approve"
    entity_type: str = Field(max_length=64)
    entity_id: str | None = Field(default=None, max_length=128)
    detail: str | None = Field(default=None, max_length=2048)


class AuditLog(AuditLogBase, table=True):
    __tablename__ = "audit_logs"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class AuditLogPublic(AuditLogBase):
    id: uuid.UUID
    created_at: datetime | None = None


class AuditLogsPublic(SQLModel):
    data: list[AuditLogPublic]
    count: int
