"""Single-file CSV snapshot of the sandbox dataset.

Exports every operational table into one `smart_forge_schema.csv` (a tall
`table,row` format where each row is the record serialized as JSON) and imports
it back to re-seed the database. Acts as a lightweight, portable data-lake
snapshot for app-wide syncing — a single file you can re-import anytime.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from sqlmodel import Session, SQLModel, delete, select

from app.models import (
    Alert,
    AskaiSession,
    AuditLog,
    CustomerMessage,
    CustomerOrder,
    Defect,
    ErpSyncEvent,
    Escalation,
    Factory,
    Incident,
    Inspection,
    InventoryItem,
    Job,
    KnowledgeDocument,
    Line,
    Machine,
    MachineConfiguration,
    MachineHealthScore,
    MesSyncEvent,
    OeeMetric,
    ProductionRun,
    PurchaseOrder,
    Quote,
    RcaRecord,
    Recommendation,
    Supplier,
    TelemetryEvent,
    WorkOrder,
)

# Parent → child order used for export and for re-insertion on import.
EXPORT_TABLES: list[tuple[str, type[SQLModel]]] = [
    ("factories", Factory),
    ("lines", Line),
    ("suppliers", Supplier),
    ("machines", Machine),
    ("inventory_items", InventoryItem),
    ("customer_orders", CustomerOrder),
    ("jobs", Job),
    ("quotes", Quote),
    ("alerts", Alert),
    ("work_orders", WorkOrder),
    ("oee_metrics", OeeMetric),
    ("production_runs", ProductionRun),
    ("inspections", Inspection),
    ("defects", Defect),
    ("machine_configurations", MachineConfiguration),
    ("recommendations", Recommendation),
    ("incidents", Incident),
    ("rca_records", RcaRecord),
    ("purchase_orders", PurchaseOrder),
    ("knowledge_documents", KnowledgeDocument),
]

_BY_NAME = dict(EXPORT_TABLES)

# Child → parent order to wipe before re-inserting. Superset of EXPORT_TABLES
# plus high-volume / dependent tables (telemetry, sync events, audit) so foreign
# keys are always satisfied. Knowledge bases are intentionally preserved.
CLEAR_MODELS: list[type] = [
    AuditLog,
    AskaiSession,
    CustomerMessage,
    Escalation,
    KnowledgeDocument,
    RcaRecord,
    PurchaseOrder,
    Recommendation,
    MachineConfiguration,
    Defect,
    Inspection,
    OeeMetric,
    ProductionRun,
    WorkOrder,
    Alert,
    MachineHealthScore,
    TelemetryEvent,
    ErpSyncEvent,
    MesSyncEvent,
    Incident,
    Quote,
    Job,
    CustomerOrder,
    InventoryItem,
    Machine,
    Supplier,
    Line,
    Factory,
]


def export_csv(session: Session) -> str:
    """Serialize all operational tables into a single tall CSV string."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["table", "row"])
    for name, model in EXPORT_TABLES:
        for row in session.exec(select(model)).all():
            writer.writerow([name, json.dumps(row.model_dump(mode="json"))])
    return buf.getvalue()


def import_csv(session: Session, content: str) -> dict[str, int]:
    """Replace all operational data with the snapshot in `content`.

    Returns a {table: rows_inserted} summary. Runs in one transaction — any
    malformed row aborts the whole import with a clear error and no changes.
    Unknown tables are ignored so a wider snapshot can still be partially loaded.
    """
    if not (content or "").strip():
        raise ValueError("Empty file")

    reader = csv.reader(io.StringIO(content))
    header = next(reader, None)
    if header != ["table", "row"]:
        raise ValueError("Unexpected CSV header — expected 'table,row'")

    # Parse + validate everything BEFORE touching the database.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for lineno, line in enumerate(reader, start=2):
        if not line or not line[0].strip():
            continue
        if len(line) < 2:
            raise ValueError(f"Malformed row at line {lineno}: expected 'table,row'")
        table, raw = line[0].strip(), line[1]
        if table not in _BY_NAME:
            continue  # ignore tables outside the known schema
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at line {lineno} ({table}): {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Row at line {lineno} ({table}) is not an object")
        grouped.setdefault(table, []).append(payload)

    # Wipe existing operational data (child → parent).
    for model in CLEAR_MODELS:
        session.exec(delete(model))

    # Re-insert the snapshot (parent → child). Flush after each table so a
    # parent's rows are persisted before any child rows reference them.
    summary: dict[str, int] = {}
    for name, model in EXPORT_TABLES:
        rows = grouped.get(name, [])
        for data in rows:
            try:
                session.add(model.model_validate(data))
            except Exception as exc:  # noqa: BLE001 — report which table failed
                raise ValueError(f"Invalid record for '{name}': {exc}") from exc
        if rows:
            session.flush()
            summary[name] = len(rows)

    session.commit()
    return summary
