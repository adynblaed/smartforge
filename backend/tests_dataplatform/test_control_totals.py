"""Numeric control-total reconciliation source -> lake -> warehouse (DQ-002).

Parquet sums use real pyarrow files in tmp dirs; warehouse/Oracle sides use
the recording fakes from conftest so every identifier and bind is auditable.
"""

from __future__ import annotations

from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.dataplatform.pipeline import reconciliation
from app.dataplatform.registry import Cadence, SyncStrategy, TableContract
from tests_dataplatform.conftest import (
    FakeEngine,
    FakeOracleConnection,
    FakeResult,
)


def write_parts(load_dir, tables: list[pa.Table]) -> None:
    load_dir.mkdir(parents=True, exist_ok=True)
    for i, table in enumerate(tables):
        pq.write_table(table, load_dir / f"part-{i:05d}.parquet")


def decimal_table(
    values: list[Decimal | None], column: str = "total_amount"
) -> pa.Table:
    return pa.table({column: pa.array(values, type=pa.decimal128(18, 2))})


@pytest.fixture
def po_contract(registry) -> TableContract:
    return registry.get("OMEGA.PURCHASE_ORDERS")


@pytest.fixture
def fake_loader(monkeypatch):
    """Recording loader engine answering counts and control-total sums."""

    def make(*, sum_scalar):
        def responder(sql, _params):
            if "audit.reconciliation_results" in sql:
                return FakeResult()
            if 'sum("' in sql:
                return FakeResult(scalar=sum_scalar)
            if "count(*)" in sql:
                return FakeResult(scalar=3)
            return None

        engine = FakeEngine(responder)
        monkeypatch.setattr(reconciliation, "loader_engine", lambda: engine)
        return engine

    return make


class TestParquetControlTotals:
    def test_decimal_sums_across_parts_with_nulls_as_zero(self, tmp_path):
        write_parts(
            tmp_path,
            [
                decimal_table([Decimal("1.10"), None, Decimal("5.50")]),
                decimal_table([Decimal("0.01"), None]),
            ],
        )
        totals = reconciliation.parquet_control_totals(tmp_path, ["total_amount"])
        assert totals == {"total_amount": Decimal("6.61")}
        assert isinstance(totals["total_amount"], Decimal)

    def test_all_null_column_sums_to_zero(self, tmp_path):
        write_parts(tmp_path, [decimal_table([None, None])])
        totals = reconciliation.parquet_control_totals(tmp_path, ["total_amount"])
        assert totals == {"total_amount": Decimal("0")}

    def test_integer_and_float_columns(self, tmp_path):
        table = pa.table(
            {
                "units_produced": pa.array([10, 20, None], type=pa.int64()),
                "qty": pa.array([0.5, 1.25, None], type=pa.float64()),
            }
        )
        write_parts(tmp_path, [table])
        totals = reconciliation.parquet_control_totals(
            tmp_path, ["units_produced", "qty"]
        )
        assert totals["units_produced"] == Decimal("30")
        assert totals["qty"] == Decimal("1.75")

    def test_missing_column_maps_to_none_not_crash(self, tmp_path):
        write_parts(tmp_path, [decimal_table([Decimal("1.00")])])
        totals = reconciliation.parquet_control_totals(
            tmp_path, ["total_amount", "not_a_column"]
        )
        assert totals["total_amount"] == Decimal("1.00")
        assert totals["not_a_column"] is None


class TestWarehouseControlTotals:
    def test_sql_quotes_identifiers_and_binds_load_id(self, po_contract, fake_loader):
        engine = fake_loader(sum_scalar=Decimal("6.61"))
        totals = reconciliation.warehouse_control_totals(
            po_contract, "20260715T100000Z_5000", ["total_amount"]
        )
        assert totals == {"total_amount": Decimal("6.61")}
        (sql, params) = engine.connection.calls[0]
        assert sql == (
            'SELECT sum("total_amount") FROM raw_oracle."purchase_orders" '
            "WHERE _load_id = :load_id"
        )
        assert params == {"load_id": "20260715T100000Z_5000"}

    def test_sql_null_sum_treated_as_zero(self, po_contract, fake_loader):
        fake_loader(sum_scalar=None)
        totals = reconciliation.warehouse_control_totals(
            po_contract, "load_1", ["total_amount"]
        )
        assert totals == {"total_amount": Decimal("0")}

    def test_uncontracted_column_rejected(self, po_contract, fake_loader):
        fake_loader(sum_scalar=Decimal("1"))
        with pytest.raises(ValueError, match="not a contracted control-total"):
            reconciliation.warehouse_control_totals(
                po_contract, "load_1", ["po_number"]
            )


class TestReconcileControlTotals:
    def _parquet(self, tmp_path):
        load_dir = tmp_path / "load_id=L1"
        write_parts(load_dir, [decimal_table([Decimal("1.10"), None, Decimal("5.51")])])
        return load_dir  # total_amount == 6.61

    def test_incremental_check_passes_on_equal_totals(
        self, tmp_path, po_contract, fake_loader
    ):
        fake_loader(sum_scalar=Decimal("6.61"))
        checks = reconciliation.reconcile_incremental(
            po_contract,
            "run_ct",
            rows_extracted=3,
            rows_written_to_lake=3,
            load_id="L1",
            load_dir=self._parquet(tmp_path),
        )
        by_name = {c["check"]: c for c in checks}
        check = by_name["control_total:total_amount"]
        assert check["passed"] is True
        assert check["source"] == Decimal("6.61")
        assert check["target"] == Decimal("6.61")

    def test_incremental_check_fails_and_persists_on_mismatch(
        self, tmp_path, po_contract, fake_loader
    ):
        engine = fake_loader(sum_scalar=Decimal("9.99"))
        checks = reconciliation.reconcile_incremental(
            po_contract,
            "run_ct",
            rows_extracted=3,
            rows_written_to_lake=3,
            load_id="L1",
            load_dir=self._parquet(tmp_path),
        )
        by_name = {c["check"]: c for c in checks}
        assert by_name["control_total:total_amount"]["passed"] is False
        # The failed check is persisted to audit.reconciliation_results.
        persisted = [
            params
            for sql, params in engine.connection.calls
            if "audit.reconciliation_results" in sql
            and params["check"] == "control_total:total_amount"
        ]
        assert len(persisted) == 1
        assert persisted[0]["passed"] is False
        assert persisted[0]["source"] == "6.61"
        assert persisted[0]["target"] == "9.99"

    def test_missing_configured_column_fails_check_without_crashing(
        self, tmp_path, po_contract, fake_loader
    ):
        fake_loader(sum_scalar=Decimal("0"))
        load_dir = tmp_path / "load_id=L2"
        write_parts(load_dir, [decimal_table([Decimal("1.00")], column="other")])
        checks = reconciliation.reconcile_incremental(
            po_contract,
            "run_ct",
            rows_extracted=1,
            rows_written_to_lake=1,
            load_id="L2",
            load_dir=load_dir,
        )
        check = next(c for c in checks if c["check"] == "control_total:total_amount")
        assert check["passed"] is False
        assert check["source"] is None

    def test_no_control_columns_or_missing_load_context_adds_no_checks(
        self, tmp_path, registry, fake_loader
    ):
        fake_loader(sum_scalar=Decimal("0"))
        machines = registry.get("OMEGA.MACHINES")  # no control_total_columns
        checks = reconciliation.reconcile_incremental(
            machines,
            "run_ct",
            rows_extracted=1,
            rows_written_to_lake=1,
            load_id="L3",
            load_dir=tmp_path,
        )
        assert not [c for c in checks if c["check"].startswith("control_total")]
        # Contracted table but legacy call without load context: also safe.
        po = registry.get("OMEGA.PURCHASE_ORDERS")
        checks = reconciliation.reconcile_incremental(
            po, "run_ct", rows_extracted=1, rows_written_to_lake=1
        )
        assert not [c for c in checks if c["check"].startswith("control_total")]

    def test_float_column_uses_absolute_tolerance(
        self, tmp_path, fake_loader, monkeypatch
    ):
        contract = TableContract(
            source_schema="OMEGA",
            source_table="FLOATY",
            cadence=Cadence.hourly,
            strategy=SyncStrategy.full_replace,
            primary_key=["ID"],
            destination_name="floaty",
            control_total_columns=["QTY"],
        )
        load_dir = tmp_path / "load_id=L4"
        write_parts(
            load_dir,
            [pa.table({"qty": pa.array([1.0, 2.0], type=pa.float64())})],
        )
        fake_loader(sum_scalar=Decimal("3.005"))  # within 0.01 of 3.0
        checks = reconciliation.reconcile_incremental(
            contract,
            "run_ct",
            rows_extracted=2,
            rows_written_to_lake=2,
            load_id="L4",
            load_dir=load_dir,
        )
        assert (
            next(c for c in checks if c["check"] == "control_total:qty")["passed"]
            is True
        )

        fake_loader(sum_scalar=Decimal("3.02"))  # outside the tolerance
        checks = reconciliation.reconcile_incremental(
            contract,
            "run_ct",
            rows_extracted=2,
            rows_written_to_lake=2,
            load_id="L4",
            load_dir=load_dir,
        )
        assert (
            next(c for c in checks if c["check"] == "control_total:qty")["passed"]
            is False
        )

    def test_decimal_totals_require_exact_equality(
        self, tmp_path, po_contract, fake_loader
    ):
        fake_loader(sum_scalar=Decimal("6.62"))  # off by one cent -> FAIL
        checks = reconciliation.reconcile_incremental(
            po_contract,
            "run_ct",
            rows_extracted=3,
            rows_written_to_lake=3,
            load_id="L1",
            load_dir=self._parquet(tmp_path),
        )
        check = next(c for c in checks if c["check"] == "control_total:total_amount")
        assert check["passed"] is False


class TestSeedSourceControlTotals:
    def test_seed_with_flashback_reconciles_oracle_sum_as_of_scn(
        self, tmp_path, po_contract, fake_loader, boundary
    ):
        fake_loader(sum_scalar=Decimal("6.61"))
        load_dir = tmp_path / "load_id=L5"
        write_parts(load_dir, [decimal_table([Decimal("1.10"), None, Decimal("5.51")])])
        oracle = FakeOracleConnection(
            script=[
                [(3,)],  # source_row_count AS OF SCN
                [(Decimal("6.61"),)],  # source control total AS OF SCN
            ]
        )
        checks = reconciliation.reconcile_seed(
            oracle,
            po_contract,
            boundary,
            3,
            "run_seed",
            use_flashback=True,
            load_id="L5",
            load_dir=load_dir,
        )
        by_name = {c["check"]: c for c in checks}
        assert by_name["control_total:total_amount"]["passed"] is True
        source_check = by_name["source_control_total:total_amount"]
        assert source_check["passed"] is True
        assert source_check["source"] == Decimal("6.61")

        sum_sql, sum_binds = oracle.cursor().executed[-1]
        assert "sum(TOTAL_AMOUNT)" in sum_sql
        assert "FROM OMEGA.PURCHASE_ORDERS" in sum_sql
        assert "AS OF SCN :scn" in sum_sql
        assert sum_binds == {"scn": boundary.scn}

    def test_seed_without_flashback_skips_source_totals(
        self, tmp_path, po_contract, fake_loader, boundary
    ):
        fake_loader(sum_scalar=Decimal("6.61"))
        load_dir = tmp_path / "load_id=L6"
        write_parts(load_dir, [decimal_table([Decimal("1.10"), None, Decimal("5.51")])])
        oracle = FakeOracleConnection(script=[[(3,)]])
        checks = reconciliation.reconcile_seed(
            oracle,
            po_contract,
            boundary,
            3,
            "run_seed",
            use_flashback=False,
            load_id="L6",
            load_dir=load_dir,
        )
        names = {c["check"] for c in checks}
        assert "control_total:total_amount" in names
        assert not any(n.startswith("source_control_total") for n in names)


class TestContractValidation:
    def _contract(self, columns):
        return TableContract(
            source_schema="OMEGA",
            source_table="X",
            cadence=Cadence.hourly,
            strategy=SyncStrategy.full_replace,
            primary_key=["ID"],
            destination_name="x",
            control_total_columns=columns,
        )

    def test_safe_identifiers_accepted(self):
        contract = self._contract(["TOTAL_AMOUNT", "QTY_2", "COL#$"])
        assert contract.control_total_columns == ["TOTAL_AMOUNT", "QTY_2", "COL#$"]

    @pytest.mark.parametrize(
        "bad",
        [
            "TOTAL AMOUNT",
            'TOTAL";DROP TABLE x;--',
            "1LEADING_DIGIT",
            "",
            "col-name",
            "sum(total)",
        ],
    )
    def test_malformed_column_names_rejected(self, bad):
        with pytest.raises(ValueError, match="unsafe control_total_columns"):
            self._contract([bad])

    def test_real_registry_contracts_all_validate_with_expected_totals(self, registry):
        assert registry.get("OMEGA.PURCHASE_ORDERS").control_total_columns == [
            "TOTAL_AMOUNT"
        ]
        assert registry.get("OMEGA.PURCHASE_ORDER_LINES").control_total_columns == [
            "LINE_AMOUNT"
        ]
        assert registry.get("OMEGA.PRODUCTION_RUNS").control_total_columns == [
            "UNITS_PRODUCED"
        ]
        for contract in registry.contracts.values():
            for column in contract.control_total_columns:
                assert column == column.upper()
