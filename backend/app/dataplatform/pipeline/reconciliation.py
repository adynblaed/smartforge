"""Reconciliation checks (Specs §22, Checklist DQ-*).

Row counts are the cheapest, highest-value check: source vs Parquet vs
warehouse must agree for every load. Contracts may additionally declare
control_total_columns: numeric sums reconciled source -> lake -> warehouse
per load (DQ-002/DBT-005), exact for decimals/integers with a small
tolerance only for floating-point columns. Results persist to
audit.reconciliation_results so drift is queryable and alertable.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import sqlalchemy as sa

from app.dataplatform.oracle.metadata import validate_identifier
from app.dataplatform.oracle.snapshot import SourceBoundary
from app.dataplatform.registry import TableContract
from app.dataplatform.warehouse.postgres import loader_engine

logger = logging.getLogger(__name__)

# Absolute tolerance for floating-point control totals only; decimal and
# integer columns must match exactly (DQ-002).
FLOAT_CONTROL_TOTAL_TOLERANCE = Decimal("0.01")


def _record(
    run_id: str,
    contract: TableContract,
    check_name: str,
    source_value: Any,
    target_value: Any,
    passed: bool,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    engine = loader_engine()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO audit.reconciliation_results
                    (run_id, source_schema, source_table, check_name,
                     source_value, target_value, passed, detail)
                VALUES (:run_id, :schema, :table, :check, :source, :target,
                        :passed, CAST(:detail AS jsonb))
                """
            ),
            {
                "run_id": run_id,
                "schema": contract.source_schema,
                "table": contract.source_table,
                "check": check_name,
                "source": str(source_value),
                "target": str(target_value),
                "passed": passed,
                "detail": json.dumps(detail or {}),
            },
        )
    return {
        "check": check_name,
        "source": source_value,
        "target": target_value,
        "passed": passed,
    }


def source_row_count(
    oracle_connection: Any,
    contract: TableContract,
    boundary: SourceBoundary,
    *,
    use_flashback: bool,
) -> int:
    schema = validate_identifier(contract.source_schema)
    table = validate_identifier(contract.source_table)
    source = f"{schema}.{table}"
    binds: dict[str, Any] = {}
    if use_flashback:
        source += " AS OF SCN :scn"
        binds["scn"] = boundary.scn
    cursor = oracle_connection.cursor()
    try:
        cursor.execute(f"SELECT count(*) FROM {source}", binds)  # noqa: S608
        return int(cursor.fetchone()[0])
    finally:
        cursor.close()


def warehouse_counts(contract: TableContract) -> tuple[int, int]:
    """(total rows, distinct PKs) in the raw warehouse table."""
    table = validate_identifier(contract.destination_name)
    pk = ", ".join(f'"{c.lower()}"' for c in contract.primary_key)
    engine = loader_engine()
    with engine.connect() as connection:
        total = connection.execute(
            sa.text(f'SELECT count(*) FROM raw_oracle."{table}"')  # noqa: S608
        ).scalar()
        distinct = connection.execute(
            sa.text(
                f"SELECT count(*) FROM (SELECT DISTINCT {pk} "  # noqa: S608
                f'FROM raw_oracle."{table}") d'
            )
        ).scalar()
    return int(total or 0), int(distinct or 0)


def max_cursor_value(contract: TableContract) -> str | None:
    if not contract.cursor_column:
        return None
    table = validate_identifier(contract.destination_name)
    cursor_col = validate_identifier(contract.cursor_column.lower())
    engine = loader_engine()
    with engine.connect() as connection:
        value = connection.execute(
            sa.text(
                f'SELECT max("{cursor_col}") FROM raw_oracle."{table}"'  # noqa: S608
            )
        ).scalar()
    return None if value is None else str(value)


def _to_decimal(value: Any) -> Decimal:
    """Lossless-enough Decimal coercion (str round-trip for floats)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def parquet_control_totals(
    load_dir: Path, columns: list[str]
) -> dict[str, Decimal | None]:
    """Sum each column across a load's part-*.parquet files (DQ-002).

    Decimal-safe: decimal128 sums remain Decimal, floats round-trip through
    str, and nulls contribute 0. A column absent from every part file maps
    to None so the caller records a failed check with a clear reason
    instead of crashing.
    """
    totals: dict[str, Decimal | None] = dict.fromkeys(columns)
    for part in sorted(load_dir.glob("part-*.parquet")):
        parquet_file = pq.ParquetFile(part)
        available = set(parquet_file.schema_arrow.names)
        wanted = [c for c in columns if c in available]
        if not wanted:
            continue
        table = pq.read_table(part, columns=wanted)
        for column in wanted:
            value = pc.sum(table.column(column)).as_py()
            increment = Decimal(0) if value is None else _to_decimal(value)
            current = totals[column]
            totals[column] = increment if current is None else current + increment
    return totals


def _parquet_float_columns(load_dir: Path, columns: list[str]) -> set[str]:
    """Columns stored as floating point in the load's Parquet schema."""
    floats: set[str] = set()
    for part in sorted(load_dir.glob("part-*.parquet")):
        schema = pq.ParquetFile(part).schema_arrow
        for column in columns:
            if column in schema.names and pa.types.is_floating(
                schema.field(column).type
            ):
                floats.add(column)
    return floats


def warehouse_control_totals(
    contract: TableContract, load_id: str, columns: list[str]
) -> dict[str, Decimal | None]:
    """Per-column sums for one load in raw_oracle.<destination> (DQ-002).

    Identifiers are quoted and come only from the contract's reviewed
    control-total allowlist; the load_id travels as a bound parameter
    (API-003 discipline). A column the warehouse cannot sum maps to None so
    the check fails with a reason instead of crashing the run.
    """
    allowed = {c.lower() for c in contract.control_total_columns}
    table = validate_identifier(contract.destination_name)
    engine = loader_engine()
    totals: dict[str, Decimal | None] = {}
    with engine.connect() as connection:
        for column in columns:
            if column.lower() not in allowed:
                raise ValueError(
                    f"Column {column!r} is not a contracted control-total "
                    f"column for {contract.qualified_name} (DQ-002)."
                )
            safe = validate_identifier(column.lower())
            try:
                value = connection.execute(
                    sa.text(
                        f'SELECT sum("{safe}") FROM raw_oracle."{table}" '  # noqa: S608
                        "WHERE _load_id = :load_id"
                    ),
                    {"load_id": load_id},
                ).scalar()
            except Exception:
                logger.exception(
                    "warehouse control total failed for %s.%s",
                    contract.qualified_name,
                    column,
                )
                totals[column] = None
                continue
            totals[column] = Decimal(0) if value is None else _to_decimal(value)
    return totals


def source_control_totals(
    oracle_connection: Any,
    contract: TableContract,
    boundary: SourceBoundary,
    columns: list[str],
) -> dict[str, Decimal | None]:
    """Oracle-side sums AS OF the captured SCN (seed flashback only, DQ-002).

    The SCN is a bound parameter; identifiers come from the contract's
    reviewed allowlist. Result keys are lowercased destination names so they
    compare directly against Parquet/warehouse totals.
    """
    schema = validate_identifier(contract.source_schema)
    table = validate_identifier(contract.source_table)
    allowed = {c.upper() for c in contract.control_total_columns}
    totals: dict[str, Decimal | None] = {}
    cursor = oracle_connection.cursor()
    try:
        for column in columns:
            if column.upper() not in allowed:
                raise ValueError(
                    f"Column {column!r} is not a contracted control-total "
                    f"column for {contract.qualified_name} (DQ-002)."
                )
            safe = validate_identifier(column.upper())
            cursor.execute(
                f"SELECT sum({safe}) FROM {schema}.{table} "  # noqa: S608
                "AS OF SCN :scn",
                {"scn": boundary.scn},
            )
            row = cursor.fetchone()
            value = row[0] if row else None
            totals[column.lower()] = Decimal(0) if value is None else _to_decimal(value)
    finally:
        cursor.close()
    return totals


def _totals_match(
    source: Decimal | None, target: Decimal | None, *, is_float: bool
) -> bool:
    """Exact equality; a small absolute tolerance for floats only (DQ-002)."""
    if source is None or target is None:
        return False
    if is_float:
        return abs(source - target) <= FLOAT_CONTROL_TOTAL_TOLERANCE
    return source == target


def _control_total_checks(
    contract: TableContract,
    run_id: str,
    *,
    load_id: str | None,
    load_dir: Path | None,
    oracle_conn: Any | None = None,
    boundary: SourceBoundary | None = None,
    use_flashback: bool = False,
) -> list[dict[str, Any]]:
    """control_total:<col> (lake vs warehouse, same load_id) and — for seeds
    with flashback — source_control_total:<col> (Oracle AS OF SCN vs lake)."""
    columns = [c.lower() for c in contract.control_total_columns]
    if not columns or load_id is None or load_dir is None:
        return []
    extracted = parquet_control_totals(load_dir, columns)
    float_columns = _parquet_float_columns(load_dir, columns)
    warehouse = warehouse_control_totals(contract, load_id, columns)
    source: dict[str, Decimal | None] = {}
    if oracle_conn is not None and boundary is not None and use_flashback:
        source = source_control_totals(oracle_conn, contract, boundary, columns)

    checks: list[dict[str, Any]] = []
    for column in columns:
        is_float = column in float_columns
        lake_total = extracted.get(column)
        wh_total = warehouse.get(column)
        reasons: list[str] = []
        if lake_total is None:
            reasons.append("column missing from extracted parquet")
        if wh_total is None:
            reasons.append("warehouse total unavailable")
        detail: dict[str, Any] = {"column": column, "load_id": load_id}
        if reasons:
            detail["reason"] = "; ".join(reasons)
        checks.append(
            _record(
                run_id,
                contract,
                f"control_total:{column}",
                lake_total,
                wh_total,
                passed=_totals_match(lake_total, wh_total, is_float=is_float),
                detail=detail,
            )
        )
        if source:
            src_total = source.get(column)
            checks.append(
                _record(
                    run_id,
                    contract,
                    f"source_control_total:{column}",
                    src_total,
                    lake_total,
                    passed=_totals_match(src_total, lake_total, is_float=is_float),
                    detail={
                        "column": column,
                        "load_id": load_id,
                        "scn": boundary.scn if boundary else None,
                    },
                )
            )
    return checks


def reconcile_seed(
    oracle_conn: Any,
    contract: TableContract,
    boundary: SourceBoundary,
    extracted_rows: int,
    run_id: str,
    *,
    use_flashback: bool,
    load_id: str | None = None,
    load_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Source vs lake vs warehouse checks after a full seed (DQ-001/003),
    plus per-load control totals when the contract declares them; seeds with
    flashback also reconcile Oracle AS OF SCN sums (DQ-002)."""
    checks: list[dict[str, Any]] = []

    src_count = source_row_count(
        oracle_conn, contract, boundary, use_flashback=use_flashback
    )
    checks.append(
        _record(
            run_id,
            contract,
            "source_vs_extracted_rowcount",
            src_count,
            extracted_rows,
            passed=(src_count == extracted_rows)
            if use_flashback
            else abs(src_count - extracted_rows) <= max(10, src_count // 1000),
            detail={"flashback": use_flashback},
        )
    )

    wh_total, wh_distinct = warehouse_counts(contract)
    checks.append(
        _record(
            run_id,
            contract,
            "extracted_vs_warehouse_rowcount",
            extracted_rows,
            wh_total,
            passed=extracted_rows == wh_total,
        )
    )
    checks.append(
        _record(
            run_id,
            contract,
            "primary_key_uniqueness",
            wh_total,
            wh_distinct,
            passed=wh_total == wh_distinct,
        )
    )
    checks.extend(
        _control_total_checks(
            contract,
            run_id,
            load_id=load_id,
            load_dir=load_dir,
            oracle_conn=oracle_conn,
            boundary=boundary,
            use_flashback=use_flashback,
        )
    )
    return checks


def reconcile_incremental(
    contract: TableContract,
    run_id: str,
    *,
    rows_extracted: int,
    rows_written_to_lake: int,
    load_id: str | None = None,
    load_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Window-level checks for incremental loads (DQ-005), plus per-load
    control totals when the contract declares them (DQ-002)."""
    checks = [
        _record(
            run_id,
            contract,
            "extracted_vs_lake_rowcount",
            rows_extracted,
            rows_written_to_lake,
            passed=rows_extracted == rows_written_to_lake,
        )
    ]
    wh_total, wh_distinct = warehouse_counts(contract)
    checks.append(
        _record(
            run_id,
            contract,
            "primary_key_uniqueness",
            wh_total,
            wh_distinct,
            passed=wh_total == wh_distinct,
        )
    )
    checks.extend(
        _control_total_checks(contract, run_id, load_id=load_id, load_dir=load_dir)
    )
    return checks
