"""Chunked, keyset-paginated Oracle extraction into Arrow batches.

Specs §10: deterministic keyset pagination (never OFFSET), bounded fetches,
explicit Arrow schemas, ingestion metadata stamped on every record, UTF-8
forced, extraction windows closed by an upper boundary.
"""

from __future__ import annotations

import datetime as dt
import decimal
import logging
from collections.abc import Iterator
from typing import Any

import oracledb
import pyarrow as pa

from app.dataplatform.oracle.metadata import (
    InferredTable,
    validate_identifier,
)
from app.dataplatform.oracle.snapshot import SourceBoundary
from app.dataplatform.registry import SurrogateUid, SyncStrategy, TableContract
from app.dataplatform.uids import surrogate_uid

logger = logging.getLogger(__name__)


def arrow_type_from_string(spec: str) -> pa.DataType:
    """Materialize the Arrow type declared in config/type_mappings.yml."""
    spec = spec.strip()
    if spec.startswith("decimal128"):
        inner = spec[len("decimal128(") : -1]
        precision_s, _, scale_s = inner.partition(",")
        return pa.decimal128(int(precision_s), int(scale_s or 0))
    if spec.startswith("timestamp"):
        if "tz=" in spec:
            return pa.timestamp("us", tz="UTC")
        return pa.timestamp("us")
    if spec.startswith("duration"):
        return pa.duration("us")
    simple: dict[str, pa.DataType] = {
        "int64": pa.int64(),
        "int32": pa.int32(),
        "float32": pa.float32(),
        "float64": pa.float64(),
        "string": pa.string(),
        "large_string": pa.large_string(),
        "binary": pa.binary(),
        "large_binary": pa.large_binary(),
        "bool": pa.bool_(),
    }
    try:
        return simple[spec]
    except KeyError:
        raise ValueError(f"Unknown Arrow type spec {spec!r}") from None


def build_arrow_schema(table: InferredTable) -> pa.Schema:
    """Explicit per-table Arrow schema — no per-batch inference (Specs §10.3).

    Layout: business columns, then contract-declared surrogate UUID columns
    (DCT-011), then ingestion metadata (DCT-012).
    """
    fields = [
        pa.field(
            c.destination_name, arrow_type_from_string(c.arrow_type), nullable=True
        )
        for c in table.columns
    ]
    fields += [
        pa.field(uid.column, pa.string(), nullable=True)
        for uid in table.contract.surrogate_uids
    ]
    fields += [
        pa.field("_source_system", pa.string()),
        pa.field("_source_schema", pa.string()),
        pa.field("_source_table", pa.string()),
        pa.field("_source_scn", pa.int64()),
        pa.field("_load_id", pa.string()),
        pa.field("_extracted_at", pa.timestamp("us", tz="UTC")),
        pa.field("_is_deleted", pa.bool_()),
    ]
    return pa.schema(fields)


def resolve_uid_key_indexes(
    contract: TableContract, columns: list[str]
) -> list[tuple[SurrogateUid, list[int]]]:
    """Positions of each surrogate-uid key column in the select list.

    Fails closed when a contracted key column is missing from the source —
    a silently NULL identity column would corrupt every downstream join.
    """
    resolved: list[tuple[SurrogateUid, list[int]]] = []
    for uid in contract.surrogate_uids:
        missing = [c for c in uid.source_columns if c not in columns]
        if missing:
            raise ValueError(
                f"{contract.qualified_name}: surrogate uid {uid.column!r} "
                f"references missing source column(s) {missing} (DCT-011)"
            )
        resolved.append((uid, [columns.index(c) for c in uid.source_columns]))
    return resolved


def surrogate_uid_arrays(
    contract: TableContract,
    uid_indexes: list[tuple[SurrogateUid, list[int]]],
    column_values: list[list[Any]],
    row_count: int,
) -> list[pa.Array]:
    """UUIDv5 arrays for one batch, computed from already-coerced values so
    the identity is stable regardless of driver value types (INC-004)."""
    arrays: list[pa.Array] = []
    for uid, indexes in uid_indexes:
        entity = uid.entity or contract.destination_name
        arrays.append(
            pa.array(
                [
                    surrogate_uid(
                        contract.source_system,
                        entity,
                        [column_values[i][r] for i in indexes],
                    )
                    for r in range(row_count)
                ],
                type=pa.string(),
            )
        )
    return arrays


def _coerce(value: Any, arrow_type: pa.DataType) -> Any:
    """Normalize driver values for the declared Arrow type."""
    if value is None:
        return None
    if pa.types.is_decimal(arrow_type) and not isinstance(value, decimal.Decimal):
        return decimal.Decimal(str(value))
    if pa.types.is_integer(arrow_type) and isinstance(value, (float, decimal.Decimal)):
        return int(value)
    if isinstance(value, oracledb.LOB):
        return value.read()
    return value


def _extraction_sql(
    contract: TableContract,
    columns: list[str],
    *,
    as_of_scn: bool,
    cursor_filter: bool,
) -> str:
    schema = validate_identifier(contract.source_schema)
    table = validate_identifier(contract.source_table)
    select_cols = ", ".join(validate_identifier(c) for c in columns)
    pk_cols = [validate_identifier(c) for c in contract.primary_key]
    source = f"{schema}.{table}"
    if as_of_scn:
        source += " AS OF SCN :snapshot_scn"

    predicates: list[str] = []
    if cursor_filter and contract.cursor_column:
        cursor_col = validate_identifier(contract.cursor_column)
        if contract.strategy is SyncStrategy.monotonic_append:
            predicates.append(f"{cursor_col} > :lower_watermark")
            predicates.append(f"{cursor_col} <= :upper_watermark")
        else:
            predicates.append(f"{cursor_col} >= :lower_watermark")
            predicates.append(f"{cursor_col} < :upper_watermark")

    # Keyset pagination over the primary key (SEED-004 / composite-safe).
    keyset_parts: list[str] = []
    for i in range(len(pk_cols)):
        equal = " AND ".join(f"{pk_cols[j]} = :last_pk_{j}" for j in range(i))
        greater = f"{pk_cols[i]} > :last_pk_{i}"
        keyset_parts.append(f"({equal + ' AND ' if equal else ''}{greater})")
    keyset = "(" + " OR ".join(keyset_parts) + ")"
    predicates.append(f"(:first_page = 1 OR {keyset})")

    where = " WHERE " + " AND ".join(predicates) if predicates else ""
    order = ", ".join(pk_cols)
    return (
        f"SELECT {select_cols} FROM {source}{where} "  # noqa: S608 - allowlisted identifiers
        f"ORDER BY {order} FETCH FIRST :batch_size ROWS ONLY"
    )


def extract_batches(
    connection: oracledb.Connection,
    inferred: InferredTable,
    boundary: SourceBoundary,
    *,
    lower_watermark: Any | None = None,
    upper_watermark: Any | None = None,
    use_flashback: bool = True,
) -> Iterator[pa.RecordBatch]:
    """Stream a table (or an incremental window) as typed Arrow batches."""
    contract = inferred.contract
    columns = [c.name for c in inferred.columns]
    dest_names = [c.destination_name for c in inferred.columns]
    schema = build_arrow_schema(inferred)
    batch_size = contract.chunk_rows
    cursor_filter = lower_watermark is not None and contract.cursor_column is not None

    sql = _extraction_sql(
        contract, columns, as_of_scn=use_flashback, cursor_filter=cursor_filter
    )
    extracted_at = dt.datetime.now(dt.timezone.utc)
    pk_indexes = [columns.index(c) for c in contract.primary_key]
    uid_indexes = resolve_uid_key_indexes(contract, columns)

    cursor = connection.cursor()
    cursor.arraysize = batch_size
    cursor.prefetchrows = batch_size + 1
    try:
        last_pk: list[Any] = [None] * len(pk_indexes)
        first_page = True
        total = 0
        while True:
            binds: dict[str, Any] = {
                "batch_size": batch_size,
                "first_page": 1 if first_page else 0,
            }
            if use_flashback:
                binds["snapshot_scn"] = boundary.scn
            if cursor_filter:
                binds["lower_watermark"] = lower_watermark
                binds["upper_watermark"] = upper_watermark
            for i, value in enumerate(last_pk):
                # NULL binds are safe on page one: the keyset predicate is
                # disabled by :first_page and NULL comparisons are never true.
                binds[f"last_pk_{i}"] = value

            cursor.execute(sql, binds)
            rows = cursor.fetchall()
            if not rows:
                break

            column_values: list[list[Any]] = [
                [None] * len(rows) for _ in inferred.columns
            ]
            for r, row in enumerate(rows):
                for c in range(len(inferred.columns)):
                    column_values[c][r] = _coerce(row[c], schema.field(c).type)

            arrays = [
                pa.array(column_values[c], type=schema.field(c).type)
                for c in range(len(inferred.columns))
            ]
            n = len(rows)
            arrays += surrogate_uid_arrays(contract, uid_indexes, column_values, n)
            arrays += [
                pa.array(["omega"] * n, type=pa.string()),
                pa.array([contract.source_schema] * n, type=pa.string()),
                pa.array([contract.source_table] * n, type=pa.string()),
                pa.array([boundary.scn] * n, type=pa.int64()),
                pa.array([boundary.load_id] * n, type=pa.string()),
                pa.array([extracted_at] * n, type=pa.timestamp("us", tz="UTC")),
                pa.array([False] * n, type=pa.bool_()),
            ]
            yield pa.RecordBatch.from_arrays(arrays, schema=schema)

            total += n
            last_row = rows[-1]
            last_pk = [last_row[i] for i in pk_indexes]
            first_page = False
            if n < batch_size:
                break
        logger.info(
            "extracted %s rows=%d load_id=%s window=[%s, %s)",
            contract.qualified_name,
            total,
            boundary.load_id,
            lower_watermark,
            upper_watermark,
        )
        _ = dest_names  # names live in the schema; kept for clarity
    finally:
        cursor.close()
