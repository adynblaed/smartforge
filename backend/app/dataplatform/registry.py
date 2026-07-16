"""Replication-contract registry.

Loads and validates config/tables.yml (per-table contracts, DCT-001) and
config/type_mappings.yml (explicit Oracle -> target type rules, DCT-002/3).
The YAML files are the reviewed source of truth; the pipeline refuses to
touch any table without a contract.
"""

from __future__ import annotations

import enum
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from app.dataplatform.config import get_platform_settings

# Mirrors app.dataplatform.oracle.metadata._IDENTIFIER_RE (ORA-008/API-003);
# duplicated here because metadata imports this module (no circular import).
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_#$]*$")


class SyncStrategy(str, enum.Enum):
    """Approved replication strategies a table contract may declare (DCT-001)."""

    updated_at_merge = "updated_at_merge"
    monotonic_append = "monotonic_append"
    full_replace = "full_replace"
    primary_key_reconcile = "primary_key_reconcile"
    hash_bucket_reconcile = "hash_bucket_reconcile"


class Cadence(str, enum.Enum):
    """Sync schedules the dispatcher may run; anything else is unschedulable."""

    hourly = "hourly"
    daily = "daily"
    weekly = "weekly"
    manual = "manual"


class DeleteStrategy(str, enum.Enum):
    """Contracted mechanism for propagating source deletes (INC-007)."""

    soft_delete = "soft_delete"
    parent_reconciliation = "parent_reconciliation"
    weekly_key_reconciliation = "weekly_key_reconciliation"
    implicit_replace = "implicit_replace"
    none = "none"


class SurrogateUid(BaseModel):
    """One contract-declared deterministic UUIDv5 column (DCT-011).

    `column` is the platform-added destination column (snake_case);
    `source_columns` are the Oracle key columns (UPPERCASE) hashed into the
    UUID; `entity` names the identified entity so cross-table references
    (a child row naming its parent's entity) reproduce the same UUID —
    it defaults to the owning table's destination_name.
    """

    column: str
    source_columns: list[str] = Field(min_length=1)
    entity: str | None = None


class TableContract(BaseModel):
    """One approved replication contract (Checklist DCT-001)."""

    source_schema: str
    source_table: str
    source_system: str = "omega"
    source_database: str = "OMEGADB"
    enabled: bool = True
    cadence: Cadence
    strategy: SyncStrategy
    primary_key: list[str] = Field(min_length=1)
    cursor_column: str | None = None
    cursor_type: str = "timestamp"
    overlap_minutes: int = 5
    chunk_rows: int = 50_000
    partition_column: str | None = None
    delete_strategy: DeleteStrategy = DeleteStrategy.none
    soft_delete_column: str | None = None
    destination_name: str
    classification: str = "internal"
    owner: str = "data-engineering"
    # Numeric columns whose sums are reconciled source -> lake -> warehouse
    # per load (DQ-002/DBT-005). Oracle column names, UPPERCASE. Additive:
    # tables without control totals keep an empty list.
    control_total_columns: list[str] = Field(default_factory=list)
    # Platform-generated deterministic UUIDv5 columns stamped at extraction
    # time (DCT-011/SEED-009); see app.dataplatform.uids. Additive.
    surrogate_uids: list[SurrogateUid] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> TableContract:
        needs_cursor = self.strategy in (
            SyncStrategy.updated_at_merge,
            SyncStrategy.monotonic_append,
        )
        if needs_cursor and not self.cursor_column:
            raise ValueError(
                f"{self.qualified_name}: strategy {self.strategy.value} "
                "requires cursor_column"
            )
        if (
            self.delete_strategy is DeleteStrategy.soft_delete
            and not self.soft_delete_column
        ):
            raise ValueError(
                f"{self.qualified_name}: delete_strategy soft_delete "
                "requires soft_delete_column"
            )
        for column in self.control_total_columns:
            # Same safe-identifier discipline as validate_identifier
            # (ORA-008/API-003): these names are quoted into SQL later.
            if not _SAFE_IDENTIFIER_RE.match(column):
                raise ValueError(
                    f"{self.qualified_name}: unsafe control_total_columns "
                    f"entry rejected: {column!r}"
                )
        seen_uid_columns: set[str] = set()
        for uid in self.surrogate_uids:
            # UID columns are quoted into DDL/SQL and share the row namespace
            # with source columns, so the same allowlist applies; a leading
            # underscore is reserved for ingestion metadata (DCT-012).
            names = [uid.column, *uid.source_columns]
            if uid.entity is not None:
                names.append(uid.entity)
            for name in names:
                if not _SAFE_IDENTIFIER_RE.match(name):
                    raise ValueError(
                        f"{self.qualified_name}: unsafe surrogate_uids "
                        f"identifier rejected: {name!r}"
                    )
            if uid.column in seen_uid_columns:
                raise ValueError(
                    f"{self.qualified_name}: duplicate surrogate_uids column "
                    f"{uid.column!r}"
                )
            seen_uid_columns.add(uid.column)
        return self

    @property
    def qualified_name(self) -> str:
        return f"{self.source_schema}.{self.source_table}"

    @property
    def raw_table(self) -> str:
        return f"raw_oracle.{self.destination_name}"

    def lake_table_dir(self, lake_published: Path) -> Path:
        return (
            lake_published
            / self.source_system
            / self.source_schema.lower()
            / self.destination_name
        )


class TypeMappingRule(BaseModel):
    """One reviewed Oracle -> Postgres/Arrow/DuckDB type rule (DCT-002)."""

    oracle: str
    when: str | None = None
    postgres: str
    arrow: str
    duckdb: str
    notes: str | None = None
    max_bytes: int | None = None
    on_oversize: str | None = None


class TypeMappings(BaseModel):
    """The reviewed type-mapping ruleset from config/type_mappings.yml.

    Resolution is first-match-wins; any type without an explicit rule fails
    closed rather than being guessed (DCT-002/DCT-008).
    """

    rules: list[TypeMappingRule]
    unsupported: list[str] = Field(default_factory=list)
    policies: dict[str, str] = Field(default_factory=dict)

    def resolve(
        self, oracle_type: str, precision: int | None, scale: int | None
    ) -> TypeMappingRule:
        """First-match-wins resolution; unmatched types fail closed (DCT-008)."""
        base_type = oracle_type.upper().split("(")[0].strip()
        if base_type in {t.upper() for t in self.unsupported}:
            raise UnsupportedOracleTypeError(oracle_type)
        for rule in self.rules:
            if rule.oracle.upper() != base_type:
                continue
            if rule.when and not _evaluate_condition(rule.when, precision, scale):
                continue
            return rule
        raise UnsupportedOracleTypeError(oracle_type)

    def render(
        self, oracle_type: str, precision: int | None, scale: int | None
    ) -> dict[str, str]:
        rule = self.resolve(oracle_type, precision, scale)
        fmt = {"precision": precision, "scale": scale}
        return {
            "postgres": rule.postgres.format(**fmt),
            "arrow": rule.arrow.format(**fmt),
            "duckdb": rule.duckdb.format(**fmt),
        }


class UnsupportedOracleTypeError(Exception):
    """Raised when discovery meets a type with no explicit mapping."""

    def __init__(self, oracle_type: str) -> None:
        super().__init__(
            f"Oracle type {oracle_type!r} has no explicit mapping in "
            "config/type_mappings.yml. Schema inference fails closed: add a "
            "reviewed mapping before replicating this column (DCT-002/DCT-008)."
        )


def _evaluate_condition(expr: str, precision: int | None, scale: int | None) -> bool:
    """Evaluate a `when:` guard against column precision/scale.

    Only the two whitelisted names are exposed; no builtins.
    """
    try:
        return bool(
            eval(  # noqa: S307 - fixed, repo-reviewed expressions only
                expr, {"__builtins__": {}}, {"precision": precision, "scale": scale}
            )
        )
    except Exception as exc:  # pragma: no cover - config authoring error
        raise ValueError(f"Invalid type-mapping condition {expr!r}: {exc}") from exc


class Registry(BaseModel):
    """All replication contracts keyed by qualified source name.

    Lookup of a table without a reviewed contract raises — the pipeline can
    never replicate an uncontracted table (DCT-001).
    """

    contracts: dict[str, TableContract]

    def get(self, qualified_name: str) -> TableContract:
        try:
            return self.contracts[qualified_name.upper()]
        except KeyError:
            raise KeyError(
                f"No replication contract for {qualified_name!r} in "
                "config/tables.yml — every table needs a reviewed contract "
                "before it can be replicated (DCT-001)."
            ) from None

    def enabled(self, cadence: Cadence | None = None) -> list[TableContract]:
        out = [c for c in self.contracts.values() if c.enabled]
        if cadence is not None:
            out = [c for c in out if c.cadence is cadence]
        return out

    def by_destination(self, destination_name: str) -> TableContract:
        for contract in self.contracts.values():
            if contract.destination_name == destination_name:
                return contract
        raise KeyError(f"No contract with destination_name={destination_name!r}")


def load_registry(path: Path | None = None) -> Registry:
    settings = get_platform_settings()
    registry_path = path or settings.tables_registry_path
    payload: dict[str, Any] = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    defaults: dict[str, Any] = payload.get("defaults", {})
    contracts: dict[str, TableContract] = {}
    for qualified, spec in payload.get("tables", {}).items():
        schema, _, table = qualified.partition(".")
        merged = {**defaults, **(spec or {})}
        merged.setdefault("source_schema", schema)
        merged.setdefault("source_table", table)
        merged.setdefault("destination_name", table.lower())
        contracts[qualified.upper()] = TableContract(**merged)
    return Registry(contracts=contracts)


def load_type_mappings(path: Path | None = None) -> TypeMappings:
    settings = get_platform_settings()
    mapping_path = path or settings.type_mappings_path
    payload = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    return TypeMappings(**payload)
