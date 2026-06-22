import uuid
from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from app.models.base import created_at_field


class DocumentKind(str, Enum):
    manual = "manual"
    sop = "sop"
    troubleshooting = "troubleshooting"
    machine_doc = "machine_doc"
    fault_note = "fault_note"


# ---- Knowledge documents (RAG corpus) ----
class KnowledgeDocumentBase(SQLModel):
    title: str = Field(max_length=255)
    kind: DocumentKind = Field(default=DocumentKind.manual)
    machine_id: uuid.UUID | None = Field(default=None, foreign_key="machine.id")
    tags: str | None = Field(default=None, max_length=512)
    content: str = Field(max_length=20000)


class KnowledgeDocumentCreate(KnowledgeDocumentBase):
    pass


class KnowledgeDocument(KnowledgeDocumentBase, table=True):
    __tablename__ = "knowledge_documents"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class KnowledgeDocumentPublic(SQLModel):
    id: uuid.UUID
    title: str
    kind: DocumentKind
    machine_id: uuid.UUID | None = None
    tags: str | None = None
    created_at: datetime | None = None


class KnowledgeDocumentsPublic(SQLModel):
    data: list[KnowledgeDocumentPublic]
    count: int


# ---- Knowledge bases (user-authored RAG sources for site-wide AskAI) ----
class KnowledgeBaseBase(SQLModel):
    name: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=512)
    content: str = Field(default="", max_length=100000)


class KnowledgeBaseCreate(KnowledgeBaseBase):
    pass


class KnowledgeBaseUpdate(SQLModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=512)
    content: str | None = Field(default=None, max_length=100000)


class KnowledgeBase(KnowledgeBaseBase, table=True):
    __tablename__ = "knowledge_bases"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()
    updated_at: datetime | None = created_at_field()


class KnowledgeBasePublic(KnowledgeBaseBase):
    id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class KnowledgeBasesPublic(SQLModel):
    data: list[KnowledgeBasePublic]
    count: int


# ---- AskAI sessions (chat threads) ----
class AskaiSessionBase(SQLModel):
    user_id: uuid.UUID | None = Field(default=None, foreign_key="user.id")
    machine_id: uuid.UUID | None = Field(default=None, foreign_key="machine.id")
    title: str | None = Field(default=None, max_length=255)


class AskaiSession(AskaiSessionBase, table=True):
    __tablename__ = "askai_sessions"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = created_at_field()


class AskaiSessionPublic(AskaiSessionBase):
    id: uuid.UUID
    created_at: datetime | None = None


# ---- AskAI request / response payloads ----
class AskRequest(SQLModel):
    question: str
    session_id: uuid.UUID | None = None
    machine_id: uuid.UUID | None = None


class SourceRef(SQLModel):
    document_id: uuid.UUID
    title: str
    kind: str  # "sop" | "forge_fact" | "document" | machine doc kind
    # Retrieved excerpt — rendered (as markdown, so images/instructions show) in
    # the collapsible source citation. Empty when not applicable.
    snippet: str = ""
    # Deep-link hints so the UI can open the exact source: SOP code (e.g.
    # "SOP-CNC-001") + section anchor for SOPs; code holds the KB id for facts.
    code: str | None = None
    anchor: str | None = None


class AskResponse(SQLModel):
    answer: str
    sources: list[SourceRef] = []
    suggested_actions: list[str] = []
    confidence: float = 1.0
    session_id: uuid.UUID | None = None


class SimFocus(SQLModel):
    """Cinematic camera directive for the Factory Simulation. After ForgeAI
    answers on the simulation page, the scene reads this to fly to / follow the
    entities the answer is about (the "Simulation Tool")."""

    # machine | fleet | logistics | inventory | none
    mode: str = "none"
    machine_ids: list[uuid.UUID] = []
    # When true the camera follows a forklift (PO / delivery / shipment queries).
    follow_forklift: bool = False
    # Short cinematic caption shown while the camera moves.
    label: str = ""


class ForgeResponse(AskResponse):
    """ForgeAI simulation-assistant answer + machine ids to highlight in-scene
    and a cinematic focus directive for the simulation camera."""

    highlight: list[uuid.UUID] = []
    focus: SimFocus | None = None
