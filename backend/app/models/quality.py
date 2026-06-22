import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import created_at_field


# ---- Inspections (AI vision inspection results) ----
class InspectionBase(SQLModel):
    part_id: str = Field(max_length=128, index=True)
    image_reference: str | None = Field(default=None, max_length=512)
    defect_detected: bool = Field(default=False)
    defect_type: str | None = Field(default=None, max_length=128)
    confidence: float = Field(default=0.0)  # 0..1
    line_id: uuid.UUID | None = Field(default=None, foreign_key="line.id", index=True)


class InspectionCreate(InspectionBase):
    pass


class Inspection(InspectionBase, table=True):
    __tablename__ = "inspections"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class InspectionPublic(InspectionBase):
    id: uuid.UUID
    created_at: datetime | None = None


class InspectionsPublic(SQLModel):
    data: list[InspectionPublic]
    count: int


# ---- Defects (tracked + correlated with scrap/rework) ----
class DefectBase(SQLModel):
    inspection_id: uuid.UUID | None = Field(
        default=None, foreign_key="inspections.id"
    )
    line_id: uuid.UUID | None = Field(default=None, foreign_key="line.id", index=True)
    defect_type: str = Field(max_length=128)
    part_id: str | None = Field(default=None, max_length=128)
    scrap_cost: float = Field(default=0.0)
    rework_cost: float = Field(default=0.0)
    is_scrap: bool = Field(default=False)
    is_rework: bool = Field(default=False)


class DefectCreate(DefectBase):
    pass


class Defect(DefectBase, table=True):
    __tablename__ = "defects"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class DefectPublic(DefectBase):
    id: uuid.UUID
    created_at: datetime | None = None


class DefectsPublic(SQLModel):
    data: list[DefectPublic]
    count: int
