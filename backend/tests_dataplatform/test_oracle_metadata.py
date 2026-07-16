"""Oracle metadata: identifier allowlist, schema hashing, DDL rendering."""

from __future__ import annotations

import pytest

from app.dataplatform.oracle.metadata import (
    INGESTION_METADATA_COLUMNS,
    validate_identifier,
)
from tests_dataplatform.conftest import MACHINE_COLUMNS, build_inferred


class TestValidateIdentifier:
    @pytest.mark.parametrize(
        "name",
        ["MACHINES", "machine_id", "T1", "A#B$C_9", "x" * 200],
    )
    def test_accepts_legal_identifiers(self, name):
        assert validate_identifier(name) == name

    @pytest.mark.parametrize(
        "name",
        [
            "PO_HEADERS; DROP TABLE USERS",
            'MACHINES"',
            "MACHINES'",
            "PO-HEADERS",
            "1TABLE",
            "_LEADING_UNDERSCORE",
            "TAB LE",
            "TAB\nLE",
            "TAB;LE",
            "TAB--LE",
            "",
        ],
    )
    def test_rejects_injection_attempts(self, name):
        with pytest.raises(ValueError, match="Unsafe SQL identifier"):
            validate_identifier(name)


class TestSchemaHash:
    def test_hash_is_stable_for_identical_columns(self, machines_contract):
        a = build_inferred(machines_contract)
        b = build_inferred(machines_contract)
        assert a.schema_hash == b.schema_hash
        assert a.schema_hash.startswith("sha256:")
        assert a.schema_hash == a.compute_schema_hash()

    def test_hash_changes_when_type_changes(self, machines_contract):
        base = build_inferred(machines_contract)
        changed_cols = [list(c) for c in MACHINE_COLUMNS]
        changed_cols[1][1] = "CLOB"  # NAME: VARCHAR2 -> CLOB
        changed = build_inferred(machines_contract, [tuple(c) for c in changed_cols])
        assert changed.schema_hash != base.schema_hash

    def test_hash_changes_when_column_renamed(self, machines_contract):
        base = build_inferred(machines_contract)
        changed_cols = [list(c) for c in MACHINE_COLUMNS]
        changed_cols[1][0] = "NAME_NEW"
        changed = build_inferred(machines_contract, [tuple(c) for c in changed_cols])
        assert changed.schema_hash != base.schema_hash

    def test_hash_changes_when_order_changes(self, machines_contract):
        base = build_inferred(machines_contract)
        reordered = build_inferred(
            machines_contract,
            [MACHINE_COLUMNS[1], MACHINE_COLUMNS[0], MACHINE_COLUMNS[2]],
        )
        assert reordered.schema_hash != base.schema_hash

    def test_hash_changes_when_nullability_changes(self, machines_contract):
        base = build_inferred(machines_contract)
        changed_cols = [list(c) for c in MACHINE_COLUMNS]
        changed_cols[1][4] = False  # NAME nullable -> NOT NULL
        changed = build_inferred(machines_contract, [tuple(c) for c in changed_cols])
        assert changed.schema_hash != base.schema_hash


class TestIngestionMetadataColumns:
    def test_required_lineage_columns_present(self):
        expected = {
            "_source_system",
            "_source_schema",
            "_source_table",
            "_source_scn",
            "_load_id",
            "_extracted_at",
            "_is_deleted",
        }
        assert expected == set(INGESTION_METADATA_COLUMNS)
        for spec in INGESTION_METADATA_COLUMNS.values():
            assert {"postgres", "arrow", "duckdb"} <= set(spec)


class TestPostgresDDL:
    def test_ddl_renders_columns_metadata_and_pk(self, machines_inferred):
        ddl = machines_inferred.postgres_ddl
        assert ddl.startswith('CREATE TABLE IF NOT EXISTS raw_oracle."machines"')
        # PK column is NOT NULL, nullable non-PK column is not.
        assert '"machine_id" BIGINT NOT NULL' in ddl
        assert '"name" TEXT NOT NULL' not in ddl
        assert '"name" TEXT' in ddl
        assert '"last_update_ts" TIMESTAMP WITHOUT TIME ZONE' in ddl
        # Ingestion metadata columns are stamped into the raw table.
        for meta_col in INGESTION_METADATA_COLUMNS:
            assert f'"{meta_col}"' in ddl
        assert 'PRIMARY KEY ("machine_id")' in ddl
        assert ddl.rstrip().endswith(");")

    def test_ddl_composite_primary_key(self, registry):
        contract = registry.get("OMEGA.PURCHASE_ORDER_LINES")
        inferred = build_inferred(
            contract,
            [
                ("PO_ID", "NUMBER", 18, 0, False, "BIGINT", "int64", "BIGINT"),
                ("LINE_NUMBER", "NUMBER", 9, 0, False, "BIGINT", "int64", "BIGINT"),
                (
                    "QTY",
                    "NUMBER",
                    12,
                    2,
                    True,
                    "NUMERIC(12,2)",
                    "decimal128(12,2)",
                    "DECIMAL(12,2)",
                ),
            ],
        )
        assert 'PRIMARY KEY ("po_id", "line_number")' in inferred.postgres_ddl

    def test_ddl_refuses_unsafe_destination_name(self, machines_contract):
        inferred = build_inferred(machines_contract)
        unsafe = machines_contract.model_copy(
            update={"destination_name": 'machines"; DROP TABLE x; --'}
        )
        inferred = inferred.model_copy(update={"contract": unsafe})
        with pytest.raises(ValueError, match="Unsafe SQL identifier"):
            _ = inferred.postgres_ddl
