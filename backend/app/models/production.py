import uuid
from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from app.models.base import created_at_field


class JobStatus(str, Enum):
    intake = "intake"
    approved = "approved"
    scheduled = "scheduled"
    in_production = "in_production"
    complete = "complete"
    cancelled = "cancelled"


# ---- Jobs (from order intake) ----
class JobBase(SQLModel):
    customer: str = Field(max_length=255)
    part_type: str = Field(max_length=255)
    quantity: int = Field(default=1)
    due_date: datetime | None = Field(default=None)
    required_materials: str | None = Field(default=None, max_length=1024)
    priority: int = Field(default=3)
    special_instructions: str | None = Field(default=None, max_length=1024)
    factory_id: uuid.UUID | None = Field(default=None, foreign_key="factory.id")
    customer_order_id: uuid.UUID | None = Field(
        default=None, foreign_key="customer_orders.id"
    )


class JobCreate(JobBase):
    pass


class Job(JobBase, table=True):
    __tablename__ = "jobs"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: JobStatus = Field(default=JobStatus.intake, index=True)
    missing_info: str | None = Field(default=None, max_length=1024)
    suggested_priority: int | None = Field(default=None)
    created_at: datetime | None = created_at_field()


class JobPublic(JobBase):
    id: uuid.UUID
    status: JobStatus
    missing_info: str | None = None
    suggested_priority: int | None = None
    created_at: datetime | None = None


class JobsPublic(SQLModel):
    data: list[JobPublic]
    count: int


# ---- Production runs ----
class ProductionRunBase(SQLModel):
    line_id: uuid.UUID = Field(foreign_key="line.id", index=True)
    machine_id: uuid.UUID | None = Field(default=None, foreign_key="machine.id")
    job_id: uuid.UUID | None = Field(default=None, foreign_key="jobs.id")
    shift: str = Field(default="A", max_length=16)
    planned_units: int = Field(default=0)
    actual_units: int = Field(default=0)
    scrap_units: int = Field(default=0)
    rework_units: int = Field(default=0)
    downtime_minutes: int = Field(default=0)


class ProductionRunCreate(ProductionRunBase):
    pass


class ProductionRun(ProductionRunBase, table=True):
    __tablename__ = "production_runs"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class ProductionRunPublic(ProductionRunBase):
    id: uuid.UUID
    created_at: datetime | None = None


class ProductionRunsPublic(SQLModel):
    data: list[ProductionRunPublic]
    count: int


# ---- OEE metrics ----
class OeeMetricBase(SQLModel):
    line_id: uuid.UUID = Field(foreign_key="line.id", index=True)
    machine_id: uuid.UUID | None = Field(default=None, foreign_key="machine.id")
    shift: str = Field(default="A", max_length=16)
    availability: float = Field(default=0.0)  # 0..1
    performance: float = Field(default=0.0)  # 0..1
    quality: float = Field(default=0.0)  # 0..1
    oee: float = Field(default=0.0)  # 0..1
    throughput: float = Field(default=0.0)
    downtime_minutes: int = Field(default=0)
    scrap_rate: float = Field(default=0.0)
    rework_rate: float = Field(default=0.0)


class OeeMetric(OeeMetricBase, table=True):
    __tablename__ = "oee_metrics"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class OeeMetricPublic(OeeMetricBase):
    id: uuid.UUID
    created_at: datetime | None = None


class OeeMetricsPublic(SQLModel):
    data: list[OeeMetricPublic]
    count: int
