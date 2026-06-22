import uuid
from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from app.models.base import created_at_field


class LineStatus(str, Enum):
    running = "running"
    idle = "idle"
    down = "down"
    maintenance = "maintenance"


class MachineStatus(str, Enum):
    running = "running"
    idle = "idle"
    fault = "fault"
    maintenance = "maintenance"
    offline = "offline"


class MaintenanceState(str, Enum):
    ok = "ok"
    due_soon = "due_soon"
    overdue = "overdue"
    in_progress = "in_progress"


class MachineType(str, Enum):
    cnc_mill = "cnc_mill"
    robotic_arm = "robotic_arm"
    hydraulic_press = "hydraulic_press"
    other = "other"


# ---- Factory ----
class FactoryBase(SQLModel):
    name: str = Field(max_length=255)
    location: str | None = Field(default=None, max_length=255)
    timezone: str = Field(default="UTC", max_length=64)


class FactoryCreate(FactoryBase):
    pass


class Factory(FactoryBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class FactoryPublic(FactoryBase):
    id: uuid.UUID
    created_at: datetime | None = None


class FactoriesPublic(SQLModel):
    data: list[FactoryPublic]
    count: int


# ---- Line ----
class LineBase(SQLModel):
    name: str = Field(max_length=255)
    status: LineStatus = Field(default=LineStatus.idle)
    factory_id: uuid.UUID = Field(foreign_key="factory.id", index=True)


class LineCreate(LineBase):
    pass


class Line(LineBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class LinePublic(LineBase):
    id: uuid.UUID
    created_at: datetime | None = None


class LinesPublic(SQLModel):
    data: list[LinePublic]
    count: int


# ---- Machine ----
class MachineBase(SQLModel):
    code: str = Field(index=True, unique=True, max_length=64)  # e.g. "cnc-01"
    name: str = Field(max_length=255)
    machine_type: MachineType = Field(default=MachineType.other)
    manufacturer: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)
    factory_id: uuid.UUID = Field(foreign_key="factory.id", index=True)
    line_id: uuid.UUID | None = Field(default=None, foreign_key="line.id", index=True)
    # Position on the 3D factory floor (metres).
    pos_x: float = Field(default=0.0)
    pos_z: float = Field(default=0.0)


class MachineCreate(MachineBase):
    pass


class MachineUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    manufacturer: str | None = None
    model: str | None = None
    line_id: uuid.UUID | None = None
    pos_x: float | None = None
    pos_z: float | None = None


class Machine(MachineBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: MachineStatus = Field(default=MachineStatus.idle)
    maintenance_state: MaintenanceState = Field(default=MaintenanceState.ok)
    health_score: float = Field(default=100.0)
    runtime_hours: float = Field(default=0.0)
    last_fault_code: str | None = Field(default=None, max_length=64)
    created_at: datetime | None = created_at_field()


class MachinePublic(MachineBase):
    id: uuid.UUID
    status: MachineStatus
    maintenance_state: MaintenanceState
    health_score: float
    runtime_hours: float
    last_fault_code: str | None = None
    created_at: datetime | None = None


class MachinesPublic(SQLModel):
    data: list[MachinePublic]
    count: int
