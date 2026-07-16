"""Sandbox sample seed: dataset integrity + the real pipeline offline.

The sample source must be internally consistent (genealogy, pegging
balances, PO totals) because it seeds the same dbt tests production data
faces; the seed itself must honor the production ordering invariants and
refuse to run outside the development environment.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from decimal import Decimal

import duckdb
import pyarrow.parquet as pq
import pytest

import app.dataplatform.pipeline.sample_seed as sample_seed_module
from app.dataplatform.pipeline.sample_seed import (
    SampleSeedRefusedError,
    run_sample_seed,
    sample_batches,
)
from app.dataplatform.sample_source import build_sample_dataset
from app.dataplatform.uids import surrogate_uid


@pytest.fixture(scope="module")
def dataset(registry):
    return build_sample_dataset(registry)


def rows_for(dataset, qualified: str):
    return dataset[qualified][1]


class TestSampleDatasetIntegrity:
    def test_every_enabled_contract_is_covered(self, registry, dataset):
        expected = {c.qualified_name for c in registry.enabled()}
        assert set(dataset) == expected

    def test_genealogy_is_three_levels_and_acyclic(self, dataset):
        rows = rows_for(dataset, "OMEGA.WORK_ORDERS")
        by_id = {r["WORK_ORDER_ID"]: r for r in rows}

        def depth(row, hops: int = 0) -> int:
            assert hops <= 3, "genealogy deeper than grandchild (or cyclic)"
            parent = row["PARENT_WORK_ORDER_ID"]
            if parent is None:
                return 0
            assert parent in by_id, f"dangling parent {parent}"
            return 1 + depth(by_id[parent], hops + 1)

        depths = {r["WORK_ORDER_ID"]: depth(r) for r in rows}
        assert set(depths.values()) == {0, 1, 2}  # roots, children, grandchildren

    def test_sales_order_pegging_references_real_roots(self, dataset):
        wos = {r["WORK_ORDER_ID"]: r for r in rows_for(dataset, "OMEGA.WORK_ORDERS")}
        for line in rows_for(dataset, "OMEGA.SALES_ORDER_LINES"):
            wo = line["WORK_ORDER_ID"]
            if wo is not None:
                assert wo in wos
                assert wos[wo]["PARENT_WORK_ORDER_ID"] is None  # pegged to roots

    def test_pegging_balances_roll_forward(self, dataset):
        """BALANCE_QTY must equal opening - demand + supply cumulatively,
        exactly what api_mrp_supply_plan recomputes with a window sum."""
        per_item: dict[str, list[dict]] = defaultdict(list)
        for row in rows_for(dataset, "OMEGA.MRP_PEGGING"):
            per_item[row["ITEM_NO"]].append(row)
        assert per_item, "pegging dataset is empty"
        for item_no, rows in per_item.items():
            opening = [r for r in rows if r["SOURCE_TYPE"] == "On Hand Quantity"]
            assert len(opening) == 1, item_no
            balance = opening[0]["BALANCE_QTY"]
            for row in rows:
                if row["SOURCE_TYPE"] == "On Hand Quantity":
                    continue
                balance += (row["SUPPLY_QTY"] or Decimal(0)) - (
                    row["DEMAND_QTY"] or Decimal(0)
                )
                assert balance == row["BALANCE_QTY"], (item_no, row)

    def test_pegging_exercises_shortage_and_wo_genealogy(self, dataset):
        rows = rows_for(dataset, "OMEGA.MRP_PEGGING")
        assert any(r["EXCEPTION_DESC"] == "Below Zero" for r in rows)
        wos = {r["WORK_ORDER_ID"] for r in rows_for(dataset, "OMEGA.WORK_ORDERS")}
        for row in rows:
            if row["WORK_ORDER_ID"] is not None:
                assert row["WORK_ORDER_ID"] in wos
            if row["PEGGED_WORK_ORDER_ID"] is not None:
                assert row["PEGGED_WORK_ORDER_ID"] in wos

    def test_po_headers_reconcile_with_lines(self, dataset):
        """assert_po_totals_reconcile (dbt) runs against this data — prove
        the invariant at the source."""
        line_sums: dict[int, Decimal] = defaultdict(lambda: Decimal(0))
        for line in rows_for(dataset, "OMEGA.PURCHASE_ORDER_LINES"):
            line_sums[line["PO_ID"]] += line["LINE_AMOUNT"]
        headers = rows_for(dataset, "OMEGA.PURCHASE_ORDERS")
        assert headers
        for header in headers:
            assert header["TOTAL_AMOUNT"] == line_sums[header["PO_ID"]]

    def test_primary_keys_unique_everywhere(self, registry, dataset):
        for qualified, (inferred, rows) in dataset.items():
            contract = inferred.contract
            keys = [tuple(r[c] for c in contract.primary_key) for r in rows]
            assert len(keys) == len(set(keys)), f"duplicate PK in {qualified}"
            for key in keys:
                assert None not in key, f"NULL PK component in {qualified}"


class TestSampleBatches:
    def test_batch_layout_and_uid_stamping(self, registry, dataset, boundary):
        inferred, rows = dataset["OMEGA.WORK_ORDERS"]
        [batch] = sample_batches(inferred, boundary, rows)
        assert batch.num_rows == len(rows)
        data = batch.to_pydict()
        by_id = dict(zip(data["work_order_id"], data["work_order_uid"], strict=True))
        for wo_id, parent_uid in zip(
            data["work_order_id"], data["parent_work_order_uid"], strict=True
        ):
            expected_uid = surrogate_uid("omega", "work_orders", [wo_id])
            assert by_id[wo_id] == expected_uid
            row = next(r for r in rows if r["WORK_ORDER_ID"] == wo_id)
            parent = row["PARENT_WORK_ORDER_ID"]
            assert parent_uid == (by_id[parent] if parent is not None else None)
        assert set(data["_load_id"]) == {boundary.load_id}
        assert set(data["_source_scn"]) == {boundary.scn}

    def test_cross_table_uid_join_key(self, dataset, boundary):
        """sales_order_lines.work_order_uid must land equal to the matching
        work_orders.work_order_uid (SEED-009-style same-identity property)."""
        wo_inferred, wo_rows = dataset["OMEGA.WORK_ORDERS"]
        sol_inferred, sol_rows = dataset["OMEGA.SALES_ORDER_LINES"]
        [wo_batch] = sample_batches(wo_inferred, boundary, wo_rows)
        [sol_batch] = sample_batches(sol_inferred, boundary, sol_rows)
        wo_uids = set(wo_batch.to_pydict()["work_order_uid"])
        sol = sol_batch.to_pydict()
        linked = [u for u in sol["work_order_uid"] if u is not None]
        assert linked, "expected sales-order lines pegged to work orders"
        assert set(linked) <= wo_uids


class TestRunSampleSeed:
    @pytest.fixture
    def lock_calls(self, monkeypatch):
        """Stub the single-flight lock (no Postgres offline), recording use."""
        calls: list[str] = []

        @contextmanager
        def fake_lock(name: str = "smartforge_pipeline"):
            calls.append(name)
            yield

        monkeypatch.setattr(sample_seed_module.state, "pipeline_lock", fake_lock)
        return calls

    @pytest.fixture
    def offline_pipeline(self, monkeypatch, platform_env, lock_calls):  # noqa: ARG002
        """Real lake + DuckDB in tmp dirs; warehouse/control mocked out."""
        loaded: list[str] = []

        def fake_load(contract, load_dir, manifest, *, settings=None):  # noqa: ARG001
            loaded.append(contract.destination_name)
            return manifest.extraction.get("row_count", 0)

        monkeypatch.setattr(sample_seed_module, "load_published_parquet", fake_load)
        monkeypatch.setattr(
            sample_seed_module, "warehouse_row_count", lambda _name: None
        )
        monkeypatch.setattr(
            sample_seed_module.reconciliation, "max_cursor_value", lambda _c: None
        )
        for fn in (
            "start_run",
            "finish_run",
            "record_table_run",
            "record_schema_version",
            "commit_watermark",
        ):
            monkeypatch.setattr(sample_seed_module.state, fn, lambda *a, **k: None)
        return loaded

    def test_full_offline_seed_publishes_and_catalogs(
        self, registry, platform_env, offline_pipeline
    ):
        result = run_sample_seed(registry=registry, with_dbt=False)
        assert result["status"] == "succeeded", result["failures"]
        assert len(result["seeded"]) == len(registry.enabled())

        # The migration KPI block rides on every run result (OBS-008).
        kpis = result["metrics"]
        assert kpis["kind"] == "sample_seed"
        assert kpis["source"] == "sample"
        assert kpis["tables_succeeded"] == len(registry.enabled())
        assert kpis["success_rate_percent"] == 100.0
        assert kpis["rows"] > 0
        assert kpis["bytes"] > 0
        assert kpis["rows_per_second"] > 0
        assert sorted(offline_pipeline) == sorted(
            c.destination_name for c in registry.enabled()
        )

        # Every table published with a manifest under an immutable load dir.
        published = platform_env.lake_published_dir
        for contract in registry.enabled():
            manifests = list(contract.lake_table_dir(published).rglob("manifest.json"))
            assert manifests, f"no manifest for {contract.qualified_name}"

        # The DuckDB catalog opens read-only and the genealogy join holds
        # inside the lake itself.
        connection = duckdb.connect(str(platform_env.DUCKDB_PATH), read_only=True)
        try:
            orphans = connection.execute(
                """
                SELECT count(*) FROM raw_oracle.work_orders c
                LEFT JOIN raw_oracle.work_orders p
                  ON c.parent_work_order_uid = p.work_order_uid
                WHERE c.parent_work_order_uid IS NOT NULL
                  AND p.work_order_uid IS NULL
                """
            ).fetchone()[0]
            assert orphans == 0
            uid_nulls = connection.execute(
                "SELECT count(*) FROM raw_oracle.work_orders "
                "WHERE work_order_uid IS NULL"
            ).fetchone()[0]
            assert uid_nulls == 0
        finally:
            connection.close()

        # Published Parquet carries the UUID columns for the MRP pegging too.
        mrp_dir = registry.get("OMEGA.MRP_PEGGING").lake_table_dir(published)
        [mrp_part] = [
            p for p in mrp_dir.rglob("part-*.parquet") if p.stat().st_size > 0
        ]
        names = pq.ParquetFile(mrp_part).schema_arrow.names
        assert {"mrp_pegging_uid", "work_order_uid", "pegged_work_order_uid"} <= set(
            names
        )

    def test_selected_tables_only(self, registry, platform_env, offline_pipeline):
        result = run_sample_seed(
            registry=registry, tables=["OMEGA.WORK_ORDERS"], with_dbt=False
        )
        assert result["status"] == "succeeded"
        assert offline_pipeline == ["work_orders"]

    def test_runs_under_the_single_flight_lock(
        self, registry, platform_env, offline_pipeline, lock_calls
    ):
        """Even the sandbox seed is a writer entry point (INC-013)."""
        run_sample_seed(registry=registry, with_dbt=False)
        assert lock_calls == ["smartforge_pipeline"]

    def test_refused_outside_development(
        self, monkeypatch, registry, platform_env, offline_pipeline
    ):
        monkeypatch.setenv("PLATFORM_ENV", "staging")
        from app.dataplatform.config import get_platform_settings

        get_platform_settings.cache_clear()
        try:
            with pytest.raises(SampleSeedRefusedError):
                run_sample_seed(registry=registry, with_dbt=False)
            assert offline_pipeline == []  # nothing moved
        finally:
            get_platform_settings.cache_clear()
