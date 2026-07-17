"""Datasource snapshot import/export — a single-file CSV data-lake snapshot."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlmodel import SQLModel, select

from app.api.deps import InternalUser, SessionDep
from app.core.features import require_feature
from app.models import (
    AuditLog,
    Customer,
    CustomerOrder,
    Escalation,
    Inspection,
    Job,
    KnowledgeDocument,
    MachineConfiguration,
    MaintenanceTicketLog,
    OeeMetric,
    ProductionRun,
    Quote,
    SopSection,
)
from app.services import snapshot
from app.services.common import write_audit

router = APIRouter(prefix="/datasources", tags=["datasources"])

# Operational tables browsable as generic read-only datasources. Sensitive
# corpora (customer chat) are intentionally excluded.
_DATASOURCE_MODELS: dict[str, type[SQLModel]] = {
    "customer_orders": CustomerOrder,
    "customers": Customer,
    "jobs": Job,
    "quotes": Quote,
    "production_runs": ProductionRun,
    "oee_metrics": OeeMetric,
    "inspections": Inspection,
    "machine_configurations": MachineConfiguration,
    "knowledge_documents": KnowledgeDocument,
    "escalations": Escalation,
    "sop_sections": SopSection,
    "ticket_logs": MaintenanceTicketLog,
    "audit_logs": AuditLog,
}
# Field names never returned in the generic view (large blobs / sensitive text).
_REDACT_FIELDS = {
    "content",
    "question",
    "answer",
    "original_ai_answer",
    "human_response",
    "body",
    "hashed_password",
}


@router.get("/table/{name}")
def read_table(
    name: str, session: SessionDep, _user: InternalUser, limit: int = 500
) -> Any:
    """Generic read-only view of an operational table for the Database Tables UI."""
    model = _DATASOURCE_MODELS.get(name)
    if model is None:
        raise HTTPException(status_code=404, detail="Unknown datasource")
    rows = session.exec(select(model).limit(limit)).all()
    data = []
    for r in rows:
        d = r.model_dump(mode="json")
        for f in _REDACT_FIELDS:
            d.pop(f, None)
        data.append(d)
    return {"data": data, "count": len(data)}


@router.get(
    "/export", dependencies=[Depends(require_feature("data_exchange"))]
)
def export_snapshot(session: SessionDep, user: InternalUser) -> Response:
    """Download every operational table as one smart_forge_schema.csv snapshot."""
    csv_text = snapshot.export_csv(session)
    write_audit(
        session,
        actor=user,
        action="datasources.export",
        entity_type="snapshot",
        detail="csv export",
    )
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=smart_forge_schema.csv",
        },
    )


@router.post(
    "/import", dependencies=[Depends(require_feature("data_exchange"))]
)
async def import_snapshot(
    session: SessionDep, user: InternalUser, file: UploadFile = File(...)
) -> Any:
    """Replace all operational data with the uploaded smart_forge_schema.csv."""
    raw = await file.read()
    # Bound the upload (defense-in-depth; nginx also caps the body at 25m).
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB).")
    try:
        summary = snapshot.import_csv(session, raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        # Validation errors are deliberately safe + user-actionable (bad
        # header, malformed row/JSON, wrong encoding) — surface them.
        session.rollback()
        raise HTTPException(status_code=400, detail=f"Import failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — surface a clean 400 to the UI
        session.rollback()
        # Don't leak internal exception/stack details to the client.
        logging.getLogger("smartforge").warning("snapshot import failed: %s", exc)
        raise HTTPException(
            status_code=400,
            detail="Import failed: the file could not be parsed. Check it is a valid snapshot CSV.",
        ) from exc
    write_audit(
        session,
        actor=user,
        action="datasources.import",
        entity_type="snapshot",
        detail=str(summary),
    )
    return {"message": "Snapshot imported", "summary": summary}
