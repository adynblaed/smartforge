"""Internal AskAI RAG chat API (spec §1C)."""

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlmodel import desc, select

from app.api.deps import InternalUser, SessionDep
from app.core.vectorstore import vector_store
from app.models import (
    AskaiSession,
    AskaiSessionPublic,
    AskRequest,
    AskResponse,
    ForgeResponse,
    KnowledgeBase,
    KnowledgeBaseCreate,
    KnowledgeBasePublic,
    KnowledgeBasesPublic,
    KnowledgeBaseUpdate,
    KnowledgeDocument,
    KnowledgeDocumentCreate,
    KnowledgeDocumentPublic,
    KnowledgeDocumentsPublic,
    Message,
)
from app.models.base import get_datetime_utc
from app.services import askai
from app.services.common import write_audit

router = APIRouter(prefix="/ask-ai", tags=["ask-ai"])


@router.post("/ask", response_model=AskResponse)
async def ask(payload: AskRequest, session: SessionDep, user: InternalUser) -> Any:
    if payload.session_id is None:
        thread = AskaiSession(user_id=user.id, machine_id=payload.machine_id,
                              title=payload.question[:80])
        session.add(thread)
        session.commit()
        session.refresh(thread)
        session_id = thread.id
    else:
        session_id = payload.session_id
    resp = await askai.answer(session, payload.question, machine_id=payload.machine_id)
    resp.session_id = session_id
    # Privacy: audit the event, not the raw question text.
    write_audit(session, actor=user, action="askai.answer",
                entity_type="askai_session", entity_id=session_id)
    return resp


@router.post("/forge", response_model=ForgeResponse)
async def forge(payload: AskRequest, session: SessionDep, user: InternalUser) -> Any:
    """ForgeAI — general simulation assistant; also returns machines to highlight."""
    resp = await askai.forge_answer(session, payload.question)
    write_audit(session, actor=user, action="forge.answer", entity_type="simulation")
    return resp


@router.get("/documents", response_model=KnowledgeDocumentsPublic)
def list_documents(session: SessionDep, _user: InternalUser) -> Any:
    rows = list(session.exec(select(KnowledgeDocument)).all())
    return KnowledgeDocumentsPublic(data=rows, count=len(rows))


@router.post("/documents", response_model=KnowledgeDocumentPublic)
def ingest_document(
    payload: KnowledgeDocumentCreate, session: SessionDep, user: InternalUser
) -> Any:
    """Ingest a manual/SOP/troubleshooting note into the RAG corpus."""
    doc = KnowledgeDocument.model_validate(payload)
    session.add(doc)
    session.commit()
    session.refresh(doc)
    write_audit(session, actor=user, action="askai.ingest_document",
                entity_type="knowledge_document", entity_id=doc.id, detail=doc.title)
    return doc


@router.get("/sessions", response_model=list[AskaiSessionPublic])
def list_sessions(session: SessionDep, user: InternalUser) -> Any:
    stmt = (
        select(AskaiSession)
        .where(AskaiSession.user_id == user.id)
        .order_by(desc(AskaiSession.created_at))
    )
    return list(session.exec(stmt).all())


# ---- Knowledge bases (user-authored RAG sources, site-wide AskAI context) ----


@router.get("/knowledge-bases", response_model=KnowledgeBasesPublic)
def list_knowledge_bases(session: SessionDep, _user: InternalUser) -> Any:
    rows = list(session.exec(select(KnowledgeBase).order_by(KnowledgeBase.name)).all())
    return KnowledgeBasesPublic(data=rows, count=len(rows))


@router.post("/knowledge-bases", response_model=KnowledgeBasePublic)
def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    session: SessionDep,
    user: InternalUser,
    tasks: BackgroundTasks,
) -> Any:
    kb = KnowledgeBase.model_validate(payload)
    session.add(kb)
    session.commit()
    session.refresh(kb)
    # Auto-vectorize into Qdrant for RAG in the background (no-op if offline).
    tasks.add_task(vector_store.upsert_kb, kb.id, kb.name, kb.content)
    write_audit(session, actor=user, action="askai.create_knowledge_base",
                entity_type="knowledge_base", entity_id=kb.id, detail=kb.name)
    return kb


@router.patch("/knowledge-bases/{kb_id}", response_model=KnowledgeBasePublic)
def update_knowledge_base(
    kb_id: uuid.UUID,
    payload: KnowledgeBaseUpdate,
    session: SessionDep,
    user: InternalUser,
    tasks: BackgroundTasks,
) -> Any:
    kb = session.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    data = payload.model_dump(exclude_unset=True)
    kb.sqlmodel_update(data)
    kb.updated_at = get_datetime_utc()
    session.add(kb)
    session.commit()
    session.refresh(kb)
    # Re-sync the vector store with the updated content (background).
    tasks.add_task(vector_store.upsert_kb, kb.id, kb.name, kb.content)
    write_audit(session, actor=user, action="askai.update_knowledge_base",
                entity_type="knowledge_base", entity_id=kb.id, detail=kb.name)
    return kb


@router.delete("/knowledge-bases/{kb_id}", response_model=Message)
def delete_knowledge_base(
    kb_id: uuid.UUID,
    session: SessionDep,
    user: InternalUser,
    tasks: BackgroundTasks,
) -> Any:
    kb = session.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    name = kb.name
    session.delete(kb)
    session.commit()
    tasks.add_task(vector_store.delete_kb, kb_id)
    write_audit(session, actor=user, action="askai.delete_knowledge_base",
                entity_type="knowledge_base", entity_id=kb_id, detail=name)
    return Message(message="Knowledge base deleted")


@router.post("/knowledge-bases/sync", response_model=Message)
def sync_knowledge_bases(session: SessionDep, user: InternalUser) -> Any:
    """Re-vectorize the full RAG index — SOPs (authoritative) + Forge Facts —
    into Qdrant from scratch. Retrieval works deterministically regardless; this
    rebuilds the semantic-search/rerank layer on top of it."""
    result = askai.reindex_rag(session)
    write_audit(session, actor=user, action="askai.sync_rag",
                entity_type="knowledge_base",
                detail=f"sop_chunks={result['sop_chunks']}, fact_chunks={result['fact_chunks']}")
    if not vector_store.available:
        return Message(
            message="Vector store unavailable — retrieval still runs deterministically."
        )
    return Message(
        message=(
            f"Re-indexed RAG: {result['sop_chunks']} SOP chunks + "
            f"{result['fact_chunks']} Forge Fact chunks."
        )
    )
