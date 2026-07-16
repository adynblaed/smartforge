"""Hard-delete reconciliation (Specs §17.2, Checklist INC-007).

A read-only cursor query can never see a deleted row, so tables whose
contract declares key reconciliation get a periodic full-key sweep: pull
the current source PK set (keys only — cheap), diff against the warehouse,
and soft-mark vanished keys with `_is_deleted = true`. Downstream dbt
staging filters deleted rows, so marts converge without physical deletes.
"""

from __future__ import annotations

import logging
from typing import Any

from app.dataplatform.oracle.connection import oracle_connection
from app.dataplatform.oracle.metadata import validate_identifier
from app.dataplatform.pipeline import state
from app.dataplatform.registry import DeleteStrategy, Registry, load_registry
from app.dataplatform.warehouse.loader import mark_deleted_keys

logger = logging.getLogger(__name__)

_RECONCILING_STRATEGIES = {
    DeleteStrategy.weekly_key_reconciliation,
    DeleteStrategy.parent_reconciliation,
}


def fetch_source_keys(connection: Any, contract: Any) -> set[tuple[Any, ...]]:
    schema = validate_identifier(contract.source_schema)
    table = validate_identifier(contract.source_table)
    columns = ", ".join(validate_identifier(c) for c in contract.primary_key)
    cursor = connection.cursor()
    cursor.arraysize = 100_000
    try:
        cursor.execute(f"SELECT {columns} FROM {schema}.{table}")  # noqa: S608
        return {tuple(row) for row in cursor.fetchall()}
    finally:
        cursor.close()


def run_delete_reconciliation(
    *,
    registry: Registry | None = None,
    cadences: list[str] | None = None,
    tables: list[str] | None = None,
) -> dict[str, Any]:
    registry = registry or load_registry()
    run_id = state.new_run_id()
    state.start_run(run_id, "reconcile", {"cadences": cadences or []})
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    selected = {t.upper() for t in tables} if tables else None
    candidates = [
        c
        for c in registry.enabled()
        if c.delete_strategy in _RECONCILING_STRATEGIES
        and (selected is None or c.qualified_name.upper() in selected)
    ]
    if not candidates:
        state.finish_run(run_id, "succeeded", {"tables": 0})
        return {"run_id": run_id, "reconciled": [], "failures": []}

    with oracle_connection() as connection:
        for contract in candidates:
            try:
                source_keys = fetch_source_keys(connection, contract)
                marked = mark_deleted_keys(contract, source_keys)
                results.append(
                    {
                        "table": contract.qualified_name,
                        "source_keys": len(source_keys),
                        "marked_deleted": marked,
                    }
                )
            except Exception as exc:
                logger.exception(
                    "delete reconciliation failed for %s", contract.qualified_name
                )
                failures.append({"table": contract.qualified_name, "error": str(exc)})

    state.finish_run(
        run_id,
        "succeeded" if not failures else "partial",
        {"reconciled": results, "failures": failures},
    )
    return {"run_id": run_id, "reconciled": results, "failures": failures}
