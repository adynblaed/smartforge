import uuid
from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from app.models.base import created_at_field


class RecommendationStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


# ---- Machine configuration profiles (versioned) ----
class MachineConfigurationBase(SQLModel):
    machine_id: uuid.UUID = Field(foreign_key="machine.id", index=True)
    speed: float = Field(default=0.0)
    temperature: float = Field(default=0.0)
    pressure: float = Field(default=0.0)
    feed_rate: float = Field(default=0.0)
    tooling_profile: str | None = Field(default=None, max_length=128)
    material_type: str | None = Field(default=None, max_length=128)


class MachineConfigurationCreate(MachineConfigurationBase):
    pass


class MachineConfiguration(MachineConfigurationBase, table=True):
    __tablename__ = "machine_configurations"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    version: int = Field(default=1)
    is_current: bool = Field(default=True)
    is_recommended: bool = Field(default=False)
    approved: bool = Field(default=False)
    performance_delta: float = Field(default=0.0)
    created_at: datetime | None = created_at_field()


class MachineConfigurationPublic(MachineConfigurationBase):
    id: uuid.UUID
    version: int
    is_current: bool
    is_recommended: bool
    approved: bool
    performance_delta: float
    created_at: datetime | None = None


class MachineConfigurationsPublic(SQLModel):
    data: list[MachineConfigurationPublic]
    count: int


# ---- Recommendations (closed-loop continuous improvement) ----
class RecommendationBase(SQLModel):
    machine_id: uuid.UUID | None = Field(default=None, foreign_key="machine.id")
    line_id: uuid.UUID | None = Field(default=None, foreign_key="line.id")
    category: str = Field(default="config", max_length=64)
    title: str = Field(max_length=255)
    detail: str | None = Field(default=None, max_length=1024)
    confidence: float = Field(default=0.5)  # 0..1


class RecommendationCreate(RecommendationBase):
    pass


class Recommendation(RecommendationBase, table=True):
    __tablename__ = "recommendations"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: RecommendationStatus = Field(
        default=RecommendationStatus.pending, index=True
    )
    outcome_impact: float | None = Field(default=None)
    created_at: datetime | None = created_at_field()


class RecommendationPublic(RecommendationBase):
    id: uuid.UUID
    status: RecommendationStatus
    outcome_impact: float | None = None
    created_at: datetime | None = None


class RecommendationsPublic(SQLModel):
    data: list[RecommendationPublic]
    count: int
