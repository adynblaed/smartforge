"""Standard Operating Procedures (SOPs).

SOPs are strict operating guidelines for SmartFactory entities (machines, lines,
processes) covering use, maintenance, troubleshooting, and process steps. They are
treated separately from the free-form knowledge corpus: each SOP is a structured,
chaptered document so the UI can deep-link straight to the relevant section.
"""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.base import created_at_field

# Allowed string values (kept as plain VARCHAR columns to avoid native DB enums).
SOP_CATEGORIES = ("operation", "maintenance", "troubleshooting", "process", "safety")
SOP_ENTITY_TYPES = ("machine", "line", "process")


class SopBase(SQLModel):
    code: str = Field(index=True, unique=True, max_length=64)  # e.g. "SOP-PRESS-001"
    title: str = Field(max_length=255)
    category: str = Field(default="maintenance", max_length=32)
    entity_type: str = Field(default="machine", max_length=32)
    machine_id: uuid.UUID | None = Field(default=None, foreign_key="machine.id", index=True)
    summary: str = Field(default="", max_length=1024)
    revision: str = Field(default="A", max_length=16)


class Sop(SopBase, table=True):
    __tablename__ = "sops"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class SopSectionBase(SQLModel):
    sop_id: uuid.UUID = Field(foreign_key="sops.id", index=True)
    anchor: str = Field(max_length=64)  # url-safe slug used for deep-link scrolling
    order_index: int = Field(default=0)
    title: str = Field(max_length=255)
    body: str = Field(default="", max_length=8000)


class SopSection(SopSectionBase, table=True):
    __tablename__ = "sop_sections"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class SopSectionPublic(SopSectionBase):
    id: uuid.UUID


class SopPublic(SopBase):
    id: uuid.UUID
    created_at: datetime | None = None


class SopDetailPublic(SopPublic):
    machine_code: str | None = None
    sections: list[SopSectionPublic] = []


class SopsPublic(SQLModel):
    data: list[SopPublic]
    count: int


# ---- Update payloads (in-place WYSIWYG editing) ----
class SopSectionUpdate(SQLModel):
    anchor: str
    title: str | None = None
    body: str | None = None


class SopUpdate(SQLModel):
    title: str | None = None
    summary: str | None = None
    sections: list[SopSectionUpdate] = []
