"""Omega source discovery and target-schema inference (Specs §7, Phase 0).

Reads Oracle dictionary views with the read-only account, validates each
contract against reality (PKs, cursor columns, types), and infers explicit
PostgreSQL / Arrow / DuckDB schemas from config/type_mappings.yml.

The output is a SeedPlan: a reviewable, hashable proposal. Nothing is
seeded until an operator confirms the plan (SEED gate, Checklist §8).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
from typing import Any

import oracledb
from pydantic import BaseModel, Field

from app.dataplatform.registry import (
    Registry,
    TableContract,
    TypeMappings,
    UnsupportedOracleTypeError,
)

logger = logging.getLogger(__name__)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_#$]*$")

# Metadata columns stamped on every landed record (Checklist DCT-012).
INGESTION_METADATA_COLUMNS: dict[str, dict[str, str]] = {
    "_source_system": {"postgres": "TEXT", "arrow": "string", "duckdb": "VARCHAR"},
    "_source_schema": {"postgres": "TEXT", "arrow": "string", "duckdb": "VARCHAR"},
    "_source_table": {"postgres": "TEXT", "arrow": "string", "duckdb": "VARCHAR"},
    "_source_scn": {"postgres": "NUMERIC", "arrow": "int64", "duckdb": "BIGINT"},
    "_load_id": {"postgres": "TEXT", "arrow": "string", "duckdb": "VARCHAR"},
    "_extracted_at": {
        "postgres": "TIMESTAMPTZ",
        "arrow": "timestamp(us, tz=UTC)",
        "duckdb": "TIMESTAMPTZ",
    },
    "_is_deleted": {"postgres": "BOOLEAN", "arrow": "bool", "duckdb": "BOOLEAN"},
}


def validate_identifier(name: str) -> str:
    """Allowlist guard for identifiers interpolated into SQL (ORA-008/API-003)."""
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier rejected: {name!r}")
    return name


class InferredColumn(BaseModel):
    """One discovered source column with its resolved target types.

    Target types come only from the reviewed mapping rules — an unmapped
    Oracle type fails discovery instead of being guessed (DCT-002/DCT-008).
    """

    name: str  # Oracle column name (UPPER)
    destination_name: str  # normalized snake_case
    oracle_type: str
    data_precision: int | None = None
    data_scale: int | None = None
    nullable: bool = True
    postgres_type: str
    arrow_type: str
    duckdb_type: str
    is_primary_key: bool = False
    warning: str | None = None


class InferredTable(BaseModel):
    """Discovered schema and verification evidence for one contracted table,
    fingerprinted (schema_hash) so later drift is detectable (DCT-007)."""

    contract: TableContract
    columns: list[InferredColumn]
    estimated_rows: int | None = None
    estimated_mb: float | None = None
    primary_key_verified: bool = False
    cursor_verified: bool = False
    schema_hash: str = ""
    warnings: list[str] = Field(default_factory=list)

    def compute_schema_hash(self) -> str:
        """Ordered-column fingerprint for drift detection (DCT-007)."""
        canonical = json.dumps(
            [
                [c.name, c.oracle_type, c.data_precision, c.data_scale, c.nullable]
                for c in self.columns
            ],
            separators=(",", ":"),
        )
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

    @property
    def postgres_ddl(self) -> str:
        """Raw-layer CREATE TABLE for the warehouse (raw_oracle schema)."""
        cols = [
            f'    "{c.destination_name}" {c.postgres_type}'
            + ("" if c.nullable and not c.is_primary_key else " NOT NULL")
            for c in self.columns
        ]
        # Contract-declared surrogate UUID columns (DCT-011); stamped at
        # extraction, so the raw layer must carry them like any column.
        cols += [f'    "{uid.column}" TEXT' for uid in self.contract.surrogate_uids]
        cols += [
            f'    "{name}" {types["postgres"]}'
            for name, types in INGESTION_METADATA_COLUMNS.items()
        ]
        pk_cols = ", ".join(
            f'"{c.destination_name}"' for c in self.columns if c.is_primary_key
        )
        constraint = f",\n    PRIMARY KEY ({pk_cols})" if pk_cols else ""
        table = validate_identifier(self.contract.destination_name)
        body = ",\n".join(cols)
        return (
            f'CREATE TABLE IF NOT EXISTS raw_oracle."{table}" (\n{body}{constraint}\n);'
        )


class SeedPlan(BaseModel):
    """A reviewable inference result; the unit of seed confirmation."""

    plan_id: str
    created_at: dt.datetime
    source_system: str = "omega"
    oracle_host: str
    oracle_service: str
    read_only_evidence: dict[str, Any] = Field(default_factory=dict)
    tables: list[InferredTable]
    blocking_issues: list[str] = Field(default_factory=list)

    @property
    def is_seedable(self) -> bool:
        return not self.blocking_issues and bool(self.tables)

    def fingerprint(self) -> str:
        canonical = json.dumps(
            sorted((t.contract.qualified_name, t.schema_hash) for t in self.tables),
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _normalize_name(oracle_name: str) -> str:
    """OMEGA-style UPPER names -> lowercase snake case (DCT-011)."""
    return oracle_name.lower()


def fetch_columns(
    connection: oracledb.Connection, schema: str, table: str
) -> list[dict[str, Any]]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT column_name, data_type, data_precision, data_scale,
                   nullable, column_id
              FROM all_tab_columns
             WHERE owner = :owner AND table_name = :table_name
             ORDER BY column_id
            """,
            {"owner": schema, "table_name": table},
        )
        return [
            {
                "column_name": row[0],
                "data_type": row[1],
                "data_precision": row[2],
                "data_scale": row[3],
                "nullable": row[4] == "Y",
            }
            for row in cursor.fetchall()
        ]
    finally:
        cursor.close()


def fetch_primary_key(
    connection: oracledb.Connection, schema: str, table: str
) -> list[str]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT cols.column_name
              FROM all_constraints con
              JOIN all_cons_columns cols
                ON cols.owner = con.owner
               AND cols.constraint_name = con.constraint_name
             WHERE con.constraint_type = 'P'
               AND con.owner = :owner
               AND con.table_name = :table_name
             ORDER BY cols.position
            """,
            {"owner": schema, "table_name": table},
        )
        return [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()


def fetch_table_stats(
    connection: oracledb.Connection, schema: str, table: str
) -> tuple[int | None, float | None]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT num_rows, blocks * 8 / 1024.0
              FROM all_tables
             WHERE owner = :owner AND table_name = :table_name
            """,
            {"owner": schema, "table_name": table},
        )
        row = cursor.fetchone()
        if row is None:
            return None, None
        return (
            int(row[0]) if row[0] is not None else None,
            float(row[1]) if row[1] is not None else None,
        )
    finally:
        cursor.close()


def infer_table(
    connection: oracledb.Connection,
    contract: TableContract,
    mappings: TypeMappings,
) -> InferredTable:
    schema = validate_identifier(contract.source_schema)
    table = validate_identifier(contract.source_table)

    raw_columns = fetch_columns(connection, schema, table)
    warnings: list[str] = []
    if not raw_columns:
        return InferredTable(
            contract=contract,
            columns=[],
            warnings=[
                f"{contract.qualified_name}: table not found or not visible to "
                "the extraction account"
            ],
        )

    source_pk = fetch_primary_key(connection, schema, table)
    pk_verified = bool(source_pk) and set(source_pk) == set(contract.primary_key)
    if not source_pk:
        warnings.append(
            f"No PRIMARY KEY constraint on {contract.qualified_name}; contract "
            f"key {contract.primary_key} must be validated for uniqueness (SRC-003)."
        )
    elif not pk_verified:
        warnings.append(
            f"Contract key {contract.primary_key} differs from source PK "
            f"{source_pk} on {contract.qualified_name} — review before seeding."
        )

    column_names = {c["column_name"] for c in raw_columns}
    cursor_verified = (
        contract.cursor_column is None or contract.cursor_column in column_names
    )
    if contract.cursor_column and not cursor_verified:
        warnings.append(
            f"Cursor column {contract.cursor_column} missing on "
            f"{contract.qualified_name} (SRC-004)."
        )
    if contract.soft_delete_column and contract.soft_delete_column not in column_names:
        warnings.append(
            f"Soft-delete column {contract.soft_delete_column} missing on "
            f"{contract.qualified_name} (SRC-005)."
        )

    inferred: list[InferredColumn] = []
    for col in raw_columns:
        try:
            rendered = mappings.render(
                col["data_type"], col["data_precision"], col["data_scale"]
            )
            warning = None
        except UnsupportedOracleTypeError as exc:
            rendered = {"postgres": "TEXT", "arrow": "string", "duckdb": "VARCHAR"}
            warning = str(exc)
            warnings.append(f"{contract.qualified_name}.{col['column_name']}: {exc}")
        inferred.append(
            InferredColumn(
                name=col["column_name"],
                destination_name=_normalize_name(col["column_name"]),
                oracle_type=col["data_type"],
                data_precision=col["data_precision"],
                data_scale=col["data_scale"],
                nullable=col["nullable"],
                postgres_type=rendered["postgres"],
                arrow_type=rendered["arrow"],
                duckdb_type=rendered["duckdb"],
                is_primary_key=col["column_name"] in contract.primary_key,
                warning=warning,
            )
        )

    rows, size_mb = fetch_table_stats(connection, schema, table)
    result = InferredTable(
        contract=contract,
        columns=inferred,
        estimated_rows=rows,
        estimated_mb=size_mb,
        primary_key_verified=pk_verified,
        cursor_verified=cursor_verified,
        warnings=warnings,
    )
    result.schema_hash = result.compute_schema_hash()
    return result


def build_seed_plan(
    connection: oracledb.Connection,
    registry: Registry,
    mappings: TypeMappings,
    *,
    oracle_host: str,
    oracle_service: str,
    read_only_evidence: dict[str, Any] | None = None,
) -> SeedPlan:
    now = dt.datetime.now(dt.timezone.utc)
    tables = [
        infer_table(connection, contract, mappings) for contract in registry.enabled()
    ]
    blocking: list[str] = []
    for table in tables:
        if not table.columns:
            blocking.extend(table.warnings)
        for column in table.columns:
            if column.warning:
                blocking.append(
                    f"{table.contract.qualified_name}.{column.name}: unmapped type "
                    f"{column.oracle_type} (fails closed)"
                )
    plan = SeedPlan(
        plan_id=now.strftime("plan_%Y%m%dT%H%M%SZ"),
        created_at=now,
        oracle_host=oracle_host,
        oracle_service=oracle_service,
        read_only_evidence=read_only_evidence or {},
        tables=tables,
        blocking_issues=blocking,
    )
    logger.info(
        "seed plan %s built: %d tables, %d blocking issues, fingerprint=%s",
        plan.plan_id,
        len(tables),
        len(blocking),
        plan.fingerprint(),
    )
    return plan
