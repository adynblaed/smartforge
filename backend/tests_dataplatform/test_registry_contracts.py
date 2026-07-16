"""Registry + type-mapping contracts against the REAL config/*.yml files."""

from __future__ import annotations

import pytest

from app.dataplatform.registry import (
    Cadence,
    DeleteStrategy,
    SyncStrategy,
    TableContract,
    TypeMappingRule,
    TypeMappings,
    UnsupportedOracleTypeError,
    _evaluate_condition,
)


class TestRealRegistry:
    def test_every_contract_validates_and_is_addressable(self, registry):
        assert len(registry.contracts) >= 12
        for qualified, contract in registry.contracts.items():
            assert isinstance(contract, TableContract)
            assert registry.get(qualified) is contract
            assert contract.primary_key, contract.qualified_name
            assert contract.destination_name == contract.destination_name.lower()

    def test_cursor_strategies_have_cursor_column(self, registry):
        for contract in registry.contracts.values():
            if contract.strategy in (
                SyncStrategy.updated_at_merge,
                SyncStrategy.monotonic_append,
            ):
                assert contract.cursor_column, contract.qualified_name

    def test_soft_delete_tables_have_soft_delete_column(self, registry):
        soft = [
            c
            for c in registry.contracts.values()
            if c.delete_strategy is DeleteStrategy.soft_delete
        ]
        assert soft, "expected at least one soft_delete contract in tables.yml"
        for contract in soft:
            assert contract.soft_delete_column, contract.qualified_name

    def test_unknown_table_fails_closed_with_contract_message(self, registry):
        with pytest.raises(KeyError, match="DCT-001"):
            registry.get("OMEGA.NOT_A_TABLE")

    def test_enabled_filters_by_cadence(self, registry):
        hourly = registry.enabled(Cadence.hourly)
        assert hourly
        assert all(c.cadence is Cadence.hourly and c.enabled for c in hourly)

    def test_by_destination_roundtrip(self, registry):
        contract = registry.by_destination("machines")
        assert contract.qualified_name == "OMEGA.MACHINES"
        with pytest.raises(KeyError):
            registry.by_destination("nope")

    def test_contract_without_cursor_column_rejected(self):
        with pytest.raises(ValueError, match="requires cursor_column"):
            TableContract(
                source_schema="OMEGA",
                source_table="X",
                cadence=Cadence.hourly,
                strategy=SyncStrategy.updated_at_merge,
                primary_key=["ID"],
                destination_name="x",
            )

    def test_soft_delete_without_column_rejected(self):
        with pytest.raises(ValueError, match="requires soft_delete_column"):
            TableContract(
                source_schema="OMEGA",
                source_table="X",
                cadence=Cadence.hourly,
                strategy=SyncStrategy.full_replace,
                primary_key=["ID"],
                delete_strategy=DeleteStrategy.soft_delete,
                destination_name="x",
            )


class TestRealTypeMappings:
    @pytest.mark.parametrize(
        ("oracle_type", "precision", "scale", "postgres", "arrow", "duckdb"),
        [
            ("NUMBER", 38, 0, "NUMERIC(38,0)", "decimal128(38,0)", "DECIMAL(38,0)"),
            ("NUMBER", 10, 0, "BIGINT", "int64", "BIGINT"),
            ("NUMBER", 10, 2, "NUMERIC(10,2)", "decimal128(10,2)", "DECIMAL(10,2)"),
            ("NUMBER", None, None, "NUMERIC", "decimal128(38,10)", "DECIMAL(38,10)"),
            ("VARCHAR2", None, None, "TEXT", "string", "VARCHAR"),
            (
                "DATE",
                None,
                None,
                "TIMESTAMP WITHOUT TIME ZONE",
                "timestamp(us)",
                "TIMESTAMP",
            ),
            (
                "TIMESTAMP(6)",
                None,
                None,
                "TIMESTAMP WITHOUT TIME ZONE",
                "timestamp(us)",
                "TIMESTAMP",
            ),
            ("CLOB", None, None, "TEXT", "large_string", "VARCHAR"),
            ("BLOB", None, None, "BYTEA", "large_binary", "BLOB"),
        ],
    )
    def test_representative_type_resolution(
        self, type_mappings, oracle_type, precision, scale, postgres, arrow, duckdb
    ):
        rendered = type_mappings.render(oracle_type, precision, scale)
        assert rendered == {"postgres": postgres, "arrow": arrow, "duckdb": duckdb}

    def test_lob_rules_carry_oversize_policy(self, type_mappings):
        rule = type_mappings.resolve("CLOB", None, None)
        assert rule.max_bytes == 16_777_216
        assert rule.on_oversize == "quarantine"

    @pytest.mark.parametrize("bad", ["SDO_GEOMETRY", "XMLTYPE", "ANYDATA", "BFILE"])
    def test_unsupported_types_fail_closed(self, type_mappings, bad):
        with pytest.raises(UnsupportedOracleTypeError, match="fails closed"):
            type_mappings.resolve(bad, None, None)

    def test_unmapped_type_fails_closed(self, type_mappings):
        with pytest.raises(UnsupportedOracleTypeError):
            type_mappings.resolve("MADE_UP_TYPE", None, None)

    def test_number_with_precision_but_null_scale_fails_closed(self, type_mappings):
        # No `when:` guard matches NUMBER(precision, scale=None): the rules
        # are deliberately exhaustive-or-fail (DCT-008).
        with pytest.raises(UnsupportedOracleTypeError):
            type_mappings.resolve("NUMBER", 10, None)

    def test_policies_present(self, type_mappings):
        assert type_mappings.policies["empty_string"] == "preserve_oracle_null"
        assert type_mappings.policies["timezone_normalization"] == "utc"


class TestConditionGuards:
    def test_when_guard_evaluates_precision_and_scale(self):
        assert _evaluate_condition("scale == 0 and precision is not None", 5, 0)
        assert not _evaluate_condition("scale == 0 and precision is not None", None, 0)
        assert not _evaluate_condition("precision is None", 5, 0)

    def test_when_guard_has_no_builtins(self):
        with pytest.raises(ValueError, match="Invalid type-mapping condition"):
            _evaluate_condition("__import__('os').system('echo pwned')", 1, 1)

    def test_when_guard_rejects_garbage_expression(self):
        with pytest.raises(ValueError, match="Invalid type-mapping condition"):
            _evaluate_condition("precision ===== scale", 1, 1)

    def test_when_guard_rejects_unknown_names(self):
        with pytest.raises(ValueError, match="Invalid type-mapping condition"):
            _evaluate_condition("open('secret')", 1, 1)

    def test_bad_when_guard_in_rule_surfaces_on_resolve(self):
        mappings = TypeMappings(
            rules=[
                TypeMappingRule(
                    oracle="NUMBER",
                    when="import os",
                    postgres="BIGINT",
                    arrow="int64",
                    duckdb="BIGINT",
                )
            ]
        )
        with pytest.raises(ValueError, match="Invalid type-mapping condition"):
            mappings.resolve("NUMBER", 5, 0)

    def test_first_match_wins_order(self, type_mappings):
        # NUMBER(18,0) must hit the BIGINT rule, not the generic NUMERIC one.
        assert type_mappings.resolve("NUMBER", 18, 0).postgres == "BIGINT"
        assert (
            type_mappings.resolve("NUMBER", 19, 0).postgres == "NUMERIC({precision},0)"
        )
