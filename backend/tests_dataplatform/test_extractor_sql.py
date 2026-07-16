"""Extractor SQL construction: bind variables, keyset pagination, windows."""

from __future__ import annotations

import re

import pyarrow as pa
import pytest

from app.dataplatform.oracle.extractor import (
    _extraction_sql,
    arrow_type_from_string,
    build_arrow_schema,
    extract_batches,
)
from tests_dataplatform.conftest import FakeOracleConnection, build_inferred


def _assert_only_bind_values(sql: str) -> None:
    """The generated SQL must contain no literal values — binds only.

    The single allowed literal is the `:first_page = 1` page-toggle constant.
    """
    assert "'" not in sql
    stripped = sql.replace(":first_page = 1", "")
    assert not re.search(r"[=<>]\s*\d", stripped), sql
    assert ":batch_size" in sql


class TestExtractionSql:
    def test_updated_at_merge_window_inequalities(self, machines_contract):
        sql = _extraction_sql(
            machines_contract,
            ["MACHINE_ID", "NAME", "LAST_UPDATE_TS"],
            as_of_scn=False,
            cursor_filter=True,
        )
        # merge windows re-read the overlap: >= lower, < upper (INC-003).
        assert "LAST_UPDATE_TS >= :lower_watermark" in sql
        assert "LAST_UPDATE_TS < :upper_watermark" in sql
        assert "> :lower_watermark" not in sql
        assert "<= :upper_watermark" not in sql
        _assert_only_bind_values(sql)

    def test_monotonic_append_window_inequalities(self, telemetry_contract):
        sql = _extraction_sql(
            telemetry_contract,
            ["EVENT_ID", "EVENT_DATE"],
            as_of_scn=False,
            cursor_filter=True,
        )
        # append-only cursors never re-read: > lower, <= upper.
        assert "EVENT_ID > :lower_watermark" in sql
        assert "EVENT_ID <= :upper_watermark" in sql
        assert ">= :lower_watermark" not in sql
        _assert_only_bind_values(sql)

    def test_as_of_scn_clause_only_when_flashback(self, machines_contract):
        flashback = _extraction_sql(
            machines_contract, ["MACHINE_ID"], as_of_scn=True, cursor_filter=False
        )
        plain = _extraction_sql(
            machines_contract, ["MACHINE_ID"], as_of_scn=False, cursor_filter=False
        )
        assert "FROM OMEGA.MACHINES AS OF SCN :snapshot_scn" in flashback
        assert "AS OF SCN" not in plain

    def test_keyset_pagination_predicate_single_pk(self, machines_contract):
        sql = _extraction_sql(
            machines_contract, ["MACHINE_ID"], as_of_scn=False, cursor_filter=False
        )
        assert "(:first_page = 1 OR ((MACHINE_ID > :last_pk_0)))" in sql
        assert "OFFSET" not in sql.upper()
        assert sql.rstrip().endswith("FETCH FIRST :batch_size ROWS ONLY")

    def test_keyset_pagination_composite_pk_lexicographic(self, registry):
        contract = registry.get("OMEGA.PURCHASE_ORDER_LINES")  # PK (PO_ID, LINE_NUMBER)
        sql = _extraction_sql(
            contract, ["PO_ID", "LINE_NUMBER"], as_of_scn=False, cursor_filter=False
        )
        assert "(PO_ID > :last_pk_0)" in sql
        assert "(PO_ID = :last_pk_0 AND LINE_NUMBER > :last_pk_1)" in sql

    def test_order_by_includes_pk_tiebreak(self, registry):
        contract = registry.get("OMEGA.PURCHASE_ORDER_LINES")
        sql = _extraction_sql(
            contract, ["PO_ID", "LINE_NUMBER"], as_of_scn=False, cursor_filter=True
        )
        assert "ORDER BY PO_ID, LINE_NUMBER" in sql

    def test_unsafe_identifiers_rejected(self, machines_contract):
        with pytest.raises(ValueError, match="Unsafe SQL identifier"):
            _extraction_sql(
                machines_contract,
                ["MACHINE_ID; DROP TABLE X"],
                as_of_scn=False,
                cursor_filter=False,
            )


class TestArrowTypes:
    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            ("int64", pa.int64()),
            ("string", pa.string()),
            ("large_string", pa.large_string()),
            ("large_binary", pa.large_binary()),
            ("bool", pa.bool_()),
            ("float64", pa.float64()),
            ("decimal128(38,0)", pa.decimal128(38, 0)),
            ("decimal128(10,2)", pa.decimal128(10, 2)),
            ("timestamp(us)", pa.timestamp("us")),
            ("timestamp(us, tz=UTC)", pa.timestamp("us", tz="UTC")),
            ("duration(us)", pa.duration("us")),
        ],
    )
    def test_arrow_type_from_string(self, spec, expected):
        assert arrow_type_from_string(spec) == expected

    def test_unknown_arrow_spec_fails_closed(self):
        with pytest.raises(ValueError, match="Unknown Arrow type spec"):
            arrow_type_from_string("varchar")

    def test_build_arrow_schema_appends_lineage_columns(self, machines_inferred):
        schema = build_arrow_schema(machines_inferred)
        assert schema.names[:3] == ["machine_id", "name", "last_update_ts"]
        assert schema.names[-7:] == [
            "_source_system",
            "_source_schema",
            "_source_table",
            "_source_scn",
            "_load_id",
            "_extracted_at",
            "_is_deleted",
        ]
        assert schema.field("machine_id").type == pa.int64()
        assert schema.field("_extracted_at").type == pa.timestamp("us", tz="UTC")


class TestExtractBatches:
    def _telemetry_inferred(self, registry):
        contract = registry.get("OMEGA.TELEMETRY_EVENTS").model_copy(
            update={"chunk_rows": 3}
        )
        return build_inferred(
            contract,
            [
                ("EVENT_ID", "NUMBER", 18, 0, False, "BIGINT", "int64", "BIGINT"),
                ("PAYLOAD", "VARCHAR2", None, None, True, "TEXT", "string", "VARCHAR"),
            ],
        )

    def test_pagination_binds_and_metadata_stamping(self, registry, boundary):
        inferred = self._telemetry_inferred(registry)
        # Page 1 full (3 rows), page 2 short (1 row) -> exactly two queries.
        connection = FakeOracleConnection(
            script=[
                [(1, "a"), (2, "b"), (3, "c")],
                [(4, "d")],
            ]
        )
        batches = list(
            extract_batches(
                connection,
                inferred,
                boundary,
                lower_watermark=0,
                upper_watermark=100,
                use_flashback=False,
            )
        )
        cursor = connection.cursor()
        assert len(cursor.executed) == 2
        sql1, binds1 = cursor.executed[0]
        sql2, binds2 = cursor.executed[1]
        assert sql1 == sql2  # one statement, values only via binds
        assert binds1["first_page"] == 1 and binds1["last_pk_0"] is None
        assert binds2["first_page"] == 0 and binds2["last_pk_0"] == 3
        for binds in (binds1, binds2):
            assert binds["batch_size"] == 3
            assert binds["lower_watermark"] == 0
            assert binds["upper_watermark"] == 100
            assert "snapshot_scn" not in binds

        assert [b.num_rows for b in batches] == [3, 1]
        table = pa.Table.from_batches(batches)
        assert table.column("event_id").to_pylist() == [1, 2, 3, 4]
        assert set(table.column("_source_scn").to_pylist()) == {boundary.scn}
        assert set(table.column("_load_id").to_pylist()) == {boundary.load_id}
        assert set(table.column("_is_deleted").to_pylist()) == {False}
        assert set(table.column("_source_table").to_pylist()) == {"TELEMETRY_EVENTS"}

    def test_flashback_seed_binds_snapshot_scn(self, registry, boundary):
        inferred = self._telemetry_inferred(registry)
        connection = FakeOracleConnection(script=[[(1, "a")]])
        list(extract_batches(connection, inferred, boundary, use_flashback=True))
        sql, binds = connection.cursor().executed[0]
        assert "AS OF SCN :snapshot_scn" in sql
        assert binds["snapshot_scn"] == boundary.scn
        # No watermark -> no cursor window in the full extract.
        assert "lower_watermark" not in binds
        assert ":lower_watermark" not in sql

    def test_zero_rows_yields_no_batches(self, registry, boundary):
        inferred = self._telemetry_inferred(registry)
        connection = FakeOracleConnection(script=[[]])
        batches = list(
            extract_batches(connection, inferred, boundary, use_flashback=False)
        )
        assert batches == []
