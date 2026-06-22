import uuid
from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from app.models.base import created_at_field


class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class AlertStatus(str, Enum):
    active = "active"
    acknowledged = "acknowledged"
    resolved = "resolved"


class WorkOrderStatus(str, Enum):
    draft = "draft"
    approved = "approved"
    rejected = "rejected"
    in_progress = "in_progress"
    completed = "completed"


class FiixSyncState(str, Enum):
    not_synced = "not_synced"
    pending = "pending"
    synced = "synced"
    failed = "failed"


# ---- Alerts ----
class AlertBase(SQLModel):
    machine_id: uuid.UUID = Field(foreign_key="machine.id", index=True)
    rule: str = Field(max_length=128)  # e.g. "high_vibration"
    severity: Severity = Field(default=Severity.medium)
    message: str = Field(max_length=512)
    recommended_action: str | None = Field(default=None, max_length=512)
    suggested_window: str | None = Field(default=None, max_length=128)


class Alert(AlertBase, table=True):
    __tablename__ = "alerts"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: AlertStatus = Field(default=AlertStatus.active, index=True)
    acknowledged_at: datetime | None = Field(default=None)
    resolved_at: datetime | None = Field(default=None)
    created_at: datetime | None = created_at_field()


class AlertPublic(AlertBase):
    id: uuid.UUID
    status: AlertStatus
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    created_at: datetime | None = None


class AlertsPublic(SQLModel):
    data: list[AlertPublic]
    count: int


# ---- Work Orders ----
class WorkOrderBase(SQLModel):
    machine_id: uuid.UUID = Field(foreign_key="machine.id", index=True)
    fault_type: str = Field(max_length=128)
    severity: Severity = Field(default=Severity.medium)
    recommended_task: str = Field(max_length=512)
    required_skill: str | None = Field(default=None, max_length=128)
    suggested_due_date: datetime | None = Field(default=None)
    source_alert_id: uuid.UUID | None = Field(
        default=None, foreign_key="alerts.id"
    )
    priority: int = Field(default=3)  # 1 (highest) .. 5 (lowest)


class WorkOrderCreate(WorkOrderBase):
    pass


class WorkOrder(WorkOrderBase, table=True):
    __tablename__ = "work_orders"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: WorkOrderStatus = Field(default=WorkOrderStatus.draft, index=True)
    fiix_sync_state: FiixSyncState = Field(default=FiixSyncState.not_synced)
    fiix_id: str | None = Field(default=None, max_length=64)
    created_at: datetime | None = created_at_field()


class WorkOrderPublic(WorkOrderBase):
    id: uuid.UUID
    status: WorkOrderStatus
    fiix_sync_state: FiixSyncState
    fiix_id: str | None = None
    created_at: datetime | None = None


class WorkOrdersPublic(SQLModel):
    data: list[WorkOrderPublic]
    count: int


# ---- Incidents & RCA ----
class IncidentBase(SQLModel):
    title: str = Field(max_length=255)
    factory_id: uuid.UUID = Field(foreign_key="factory.id", index=True)
    affected_machines: str | None = Field(default=None, max_length=1024)  # csv ids
    affected_jobs: str | None = Field(default=None, max_length=1024)
    delayed_orders: int = Field(default=0)
    downtime_minutes: int = Field(default=0)
    estimated_cost: float = Field(default=0.0)
    severity: Severity = Field(default=Severity.high)


class IncidentCreate(IncidentBase):
    pass


class Incident(IncidentBase, table=True):
    __tablename__ = "incidents"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    resolved: bool = Field(default=False)
    created_at: datetime | None = created_at_field()


class IncidentPublic(IncidentBase):
    id: uuid.UUID
    resolved: bool
    created_at: datetime | None = None


class IncidentsPublic(SQLModel):
    data: list[IncidentPublic]
    count: int


class RcaRecordBase(SQLModel):
    incident_id: uuid.UUID = Field(foreign_key="incidents.id", index=True)
    root_cause: str = Field(max_length=1024)
    corrective_actions: str | None = Field(default=None, max_length=1024)
    timeline_note: str | None = Field(default=None, max_length=1024)


class RcaRecordCreate(SQLModel):
    # incident_id comes from the URL path, not the request body.
    root_cause: str = Field(max_length=1024)
    corrective_actions: str | None = Field(default=None, max_length=1024)
    timeline_note: str | None = Field(default=None, max_length=1024)


class RcaRecord(RcaRecordBase, table=True):
    __tablename__ = "rca_records"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class RcaRecordPublic(RcaRecordBase):
    id: uuid.UUID
    created_at: datetime | None = None


class RcaRecordsPublic(SQLModel):
    data: list[RcaRecordPublic]
    count: int
