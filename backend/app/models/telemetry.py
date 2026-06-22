import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import created_at_field
from app.models.factory import LineStatus, MaintenanceState


# ---- Telemetry events (simulated OPC/PLC ingestion) ----
class TelemetryEventBase(SQLModel):
    machine_id: uuid.UUID = Field(foreign_key="machine.id", index=True)
    temperature: float = Field(default=0.0)  # celsius
    vibration: float = Field(default=0.0)  # vibration index
    cycle_time: float = Field(default=0.0)  # seconds
    runtime_hours: float = Field(default=0.0)
    fault_code: str | None = Field(default=None, max_length=64)
    power_draw: float = Field(default=0.0)  # kW
    line_status: LineStatus = Field(default=LineStatus.idle)
    maintenance_state: MaintenanceState = Field(default=MaintenanceState.ok)


class TelemetryEventCreate(TelemetryEventBase):
    pass


class TelemetryEvent(TelemetryEventBase, table=True):
    __tablename__ = "telemetry_events"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class TelemetryEventPublic(TelemetryEventBase):
    id: uuid.UUID
    created_at: datetime | None = None


class TelemetryEventsPublic(SQLModel):
    data: list[TelemetryEventPublic]
    count: int


# ---- Machine health score history ----
class MachineHealthScoreBase(SQLModel):
    machine_id: uuid.UUID = Field(foreign_key="machine.id", index=True)
    score: float = Field(default=100.0)
    fault_frequency: float = Field(default=0.0)
    vibration_trend: float = Field(default=0.0)
    temperature_trend: float = Field(default=0.0)
    missed_maintenance: int = Field(default=0)
    production_interruptions: int = Field(default=0)
    downtime_risk: float = Field(default=0.0)  # 0..1


class MachineHealthScore(MachineHealthScoreBase, table=True):
    __tablename__ = "machine_health_scores"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class MachineHealthScorePublic(MachineHealthScoreBase):
    id: uuid.UUID
    created_at: datetime | None = None


class MachineHealthScoresPublic(SQLModel):
    data: list[MachineHealthScorePublic]
    count: int
