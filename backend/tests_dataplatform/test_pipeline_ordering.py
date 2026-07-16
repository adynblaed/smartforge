"""Pipeline ordering / idempotency for incremental sync and full seed.

Every collaborator (extractor, lake, loader, reconciliation, state) is
replaced by a recording fake so the tests assert pure orchestration:
  * drift check happens BEFORE extraction (incremental);
  * extract -> stage-validate -> publish -> warehouse load -> reconcile ->
    watermark commit LAST;
  * a failure injected at any earlier stage means the watermark is NEVER
    committed;
  * schema drift pauses one table while others continue.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.dataplatform.lake import parquet as lake_parquet
from app.dataplatform.pipeline import full_seed, incremental, reconciliation, state
from app.dataplatform.registry import Registry
from tests_dataplatform.conftest import build_inferred


class Recorder:
    """Chronological call log with optional per-stage failure injection."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_at: str | None = None

    def hit(self, name: str) -> None:
        self.calls.append(name)
        if name == self.fail_at:
            raise RuntimeError(f"injected failure at {name}")

    def index(self, name: str) -> int:
        return self.calls.index(name)

    def assert_order(self, *names: str) -> None:
        indexes = [self.index(n) for n in names]
        assert indexes == sorted(indexes), f"expected order {names}, got {self.calls}"


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


def _write_result(rows: int = 4):
    return SimpleNamespace(
        row_count=rows,
        file_count=1,
        total_bytes=100,
        files=[{"path": "part-00000.parquet", "rows": rows, "bytes": 100}],
    )


def _wire_incremental(
    monkeypatch,
    recorder,
    machines_inferred,
    boundary,
    make_settings,
    *,
    drift: bool = False,
    reconcile_passed: bool = True,
):
    settings = make_settings()
    monkeypatch.setattr(incremental, "get_platform_settings", lambda: settings)
    monkeypatch.setattr(incremental, "load_type_mappings", lambda: None)

    @contextmanager
    def fake_oracle_connection():
        yield SimpleNamespace(name="fake-oracle")

    monkeypatch.setattr(incremental, "oracle_connection", fake_oracle_connection)
    monkeypatch.setattr(
        incremental,
        "infer_table",
        lambda conn, contract, mappings: (
            recorder.hit("infer_table") or machines_inferred
        ),
    )
    monkeypatch.setattr(
        state,
        "record_schema_version",
        lambda contract, schema_hash, columns: recorder.hit("drift_check") or drift,
    )
    monkeypatch.setattr(
        incremental,
        "capture_boundary",
        lambda conn: recorder.hit("capture_boundary") or boundary,
    )
    monkeypatch.setattr(
        state,
        "get_watermark",
        lambda contract: (
            recorder.hit("get_watermark") or state.Watermark(None, None, None, None)
        ),
    )
    monkeypatch.setattr(
        state,
        "record_table_run",
        lambda run_id, load_id, contract, *, status, **kw: recorder.hit(
            f"record_table_run:{status}"
        ),
    )
    monkeypatch.setattr(incremental, "build_arrow_schema", lambda inferred: object())
    monkeypatch.setattr(
        incremental,
        "extract_batches",
        lambda *a, **k: recorder.hit("extract") or iter(()),
    )
    monkeypatch.setattr(
        lake_parquet,
        "write_staged_load",
        lambda batches, schema, *, load_id, table_name, settings=None: (
            recorder.hit("stage_write")
            or (Path("staging") / table_name, _write_result())
        ),
    )
    monkeypatch.setattr(
        lake_parquet,
        "validate_staged_load",
        lambda staging_dir, expected: recorder.hit("stage_validate"),
    )
    monkeypatch.setattr(
        lake_parquet,
        "publish_load",
        lambda staging_dir, inferred, bnd, manifest, *, kind, settings=None: (
            recorder.hit("publish") or Path("published") / "load"
        ),
    )
    monkeypatch.setattr(
        incremental,
        "load_published_parquet",
        lambda contract, load_dir, manifest, *, settings=None: (
            recorder.hit("warehouse_load") or 4
        ),
    )
    monkeypatch.setattr(
        reconciliation,
        "reconcile_incremental",
        lambda contract, run_id, *, rows_extracted, rows_written_to_lake, **_kw: (
            recorder.hit("reconcile") or [{"passed": reconcile_passed}]
        ),
    )
    monkeypatch.setattr(
        reconciliation,
        "max_cursor_value",
        lambda contract: recorder.hit("max_cursor_value") or "2026-07-15T09:00:00",
    )
    monkeypatch.setattr(
        state,
        "commit_watermark",
        lambda contract, *, cursor_value, source_scn, load_id: recorder.hit(
            "commit_watermark"
        ),
    )
    return settings


class TestIncrementalOrdering:
    def test_successful_sync_call_order(
        self,
        monkeypatch,
        recorder,
        machines_inferred,
        boundary,
        make_settings,
        machines_contract,
    ):
        _wire_incremental(
            monkeypatch, recorder, machines_inferred, boundary, make_settings
        )
        result = incremental.sync_table(machines_contract, "run_1")
        assert result["rows"] == 4
        assert result["load_id"] == boundary.load_id

        # Drift check strictly before extraction (DCT-007).
        recorder.assert_order("infer_table", "drift_check", "extract")
        # The commit sequence, watermark strictly last.
        recorder.assert_order(
            "extract",
            "stage_write",
            "stage_validate",
            "publish",
            "warehouse_load",
            "reconcile",
            "commit_watermark",
        )
        # The watermark commit is the FINAL state transition apart from the
        # bookkeeping record of success.
        after_commit = recorder.calls[recorder.index("commit_watermark") + 1 :]
        assert after_commit == ["record_table_run:succeeded"]

    def test_schema_drift_aborts_before_extraction(
        self,
        monkeypatch,
        recorder,
        machines_inferred,
        boundary,
        make_settings,
        machines_contract,
    ):
        _wire_incremental(
            monkeypatch,
            recorder,
            machines_inferred,
            boundary,
            make_settings,
            drift=True,
        )
        with pytest.raises(RuntimeError, match="Schema drift"):
            incremental.sync_table(machines_contract, "run_1")
        assert "extract" not in recorder.calls
        assert "commit_watermark" not in recorder.calls

    @pytest.mark.parametrize(
        "failure_stage",
        [
            "infer_table",
            "extract",
            "stage_write",
            "stage_validate",
            "publish",
            "warehouse_load",
            "reconcile",
        ],
    )
    def test_watermark_never_commits_on_injected_failure(
        self,
        monkeypatch,
        recorder,
        machines_inferred,
        boundary,
        make_settings,
        machines_contract,
        failure_stage,
    ):
        _wire_incremental(
            monkeypatch, recorder, machines_inferred, boundary, make_settings
        )
        recorder.fail_at = failure_stage
        with pytest.raises(RuntimeError, match="injected failure"):
            incremental.sync_table(machines_contract, "run_1")
        assert "commit_watermark" not in recorder.calls
        assert "record_table_run:succeeded" not in recorder.calls

    def test_failed_reconciliation_blocks_watermark(
        self,
        monkeypatch,
        recorder,
        machines_inferred,
        boundary,
        make_settings,
        machines_contract,
    ):
        _wire_incremental(
            monkeypatch,
            recorder,
            machines_inferred,
            boundary,
            make_settings,
            reconcile_passed=False,
        )
        with pytest.raises(RuntimeError, match="reconciliation failed"):
            incremental.sync_table(machines_contract, "run_1")
        assert "commit_watermark" not in recorder.calls
        assert "record_table_run:failed" in recorder.calls


class TestRunIncrementalIsolation:
    def test_drifted_table_pauses_while_others_continue(self, monkeypatch, registry):
        contracts = Registry(
            contracts={
                "OMEGA.WORK_ORDERS": registry.get("OMEGA.WORK_ORDERS"),
                "OMEGA.DEFECTS": registry.get("OMEGA.DEFECTS"),
                "OMEGA.PRODUCTION_RUNS": registry.get("OMEGA.PRODUCTION_RUNS"),
            }
        )
        synced: list[str] = []

        def fake_sync_table(contract, _run_id):
            if contract.source_table == "DEFECTS":
                raise RuntimeError(
                    "Schema drift detected on OMEGA.DEFECTS; table paused"
                )
            synced.append(contract.qualified_name)
            return {
                "table": contract.qualified_name,
                "rows": 1,
                "load_id": "l",
                "window": [],
            }

        monkeypatch.setattr(incremental, "sync_table", fake_sync_table)
        monkeypatch.setattr(state, "new_run_id", lambda: "run_test")
        monkeypatch.setattr(state, "start_run", lambda *a, **k: None)
        finishes: list[tuple] = []
        monkeypatch.setattr(
            state,
            "finish_run",
            lambda run_id, status, detail=None: finishes.append(
                (run_id, status, detail)
            ),
        )
        refreshed: list[bool] = []
        monkeypatch.setattr(
            incremental, "refresh_catalog", lambda reg: refreshed.append(True)
        )

        result = incremental.run_incremental(["hourly"], registry=contracts)
        assert sorted(synced) == ["OMEGA.PRODUCTION_RUNS", "OMEGA.WORK_ORDERS"]
        assert len(result["failures"]) == 1
        assert result["failures"][0]["table"] == "OMEGA.DEFECTS"
        assert "Schema drift" in result["failures"][0]["error"]
        # The run is partial, not failed: healthy tables kept flowing.
        assert len(finishes) == 1
        run_id, status, detail = finishes[0]
        assert (run_id, status) == ("run_test", "partial")
        assert detail["synced"] == 2
        assert detail["failures"] == result["failures"]
        # The migration KPI block rides on the run record (OBS-008).
        assert detail["metrics"]["tables_failed"] == 1
        assert detail["metrics"]["success_rate_percent"] == pytest.approx(66.7)
        assert refreshed == [True]

    def test_all_failures_marks_run_failed(self, monkeypatch, registry):
        contracts = Registry(
            contracts={"OMEGA.WORK_ORDERS": registry.get("OMEGA.WORK_ORDERS")}
        )
        monkeypatch.setattr(
            incremental,
            "sync_table",
            lambda contract, run_id: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        monkeypatch.setattr(state, "new_run_id", lambda: "run_test")
        monkeypatch.setattr(state, "start_run", lambda *a, **k: None)
        statuses: list[str] = []
        monkeypatch.setattr(
            state,
            "finish_run",
            lambda run_id, status, detail=None: statuses.append(status),
        )
        monkeypatch.setattr(
            incremental,
            "refresh_catalog",
            lambda reg: pytest.fail("catalog must not refresh when nothing synced"),
        )
        result = incremental.run_incremental(["hourly"], registry=contracts)
        assert statuses == ["failed"]
        assert result["synced"] == []


def _wire_seed(
    monkeypatch,
    recorder,
    boundary,  # noqa: ARG001
    make_settings,
    *,
    reconcile_passed: bool = True,
):
    settings = make_settings()
    monkeypatch.setattr(full_seed, "get_platform_settings", lambda: settings)
    monkeypatch.setattr(
        state,
        "record_table_run",
        lambda run_id, load_id, contract, *, status, **kw: recorder.hit(
            f"record_table_run:{status}"
        ),
    )
    monkeypatch.setattr(full_seed, "build_arrow_schema", lambda inferred: object())
    monkeypatch.setattr(
        full_seed,
        "extract_batches",
        lambda *a, **k: recorder.hit("extract") or iter(()),
    )
    monkeypatch.setattr(
        lake_parquet,
        "write_staged_load",
        lambda batches, schema, *, load_id, table_name, settings=None: (
            recorder.hit("stage_write")
            or (Path("staging") / table_name, _write_result())
        ),
    )
    monkeypatch.setattr(
        lake_parquet,
        "validate_staged_load",
        lambda staging_dir, expected: recorder.hit("stage_validate"),
    )
    monkeypatch.setattr(
        lake_parquet,
        "publish_load",
        lambda staging_dir, inferred, bnd, manifest, *, kind, settings=None: (
            recorder.hit("publish") or Path("published") / "load"
        ),
    )
    monkeypatch.setattr(
        full_seed,
        "load_published_parquet",
        lambda contract, load_dir, manifest, *, settings=None: (
            recorder.hit("warehouse_load") or 4
        ),
    )
    monkeypatch.setattr(
        state,
        "record_schema_version",
        lambda contract, schema_hash, columns: (
            recorder.hit("record_schema_version") or False
        ),
    )
    monkeypatch.setattr(
        reconciliation,
        "reconcile_seed",
        lambda conn, contract, bnd, rows, run_id, *, use_flashback, **_kw: (
            recorder.hit("reconcile") or [{"passed": reconcile_passed}]
        ),
    )
    monkeypatch.setattr(
        reconciliation,
        "max_cursor_value",
        lambda contract: recorder.hit("max_cursor_value") or "2026-07-15T09:00:00",
    )
    monkeypatch.setattr(
        state,
        "commit_watermark",
        lambda contract, *, cursor_value, source_scn, load_id: recorder.hit(
            "commit_watermark"
        ),
    )
    return settings


class TestSeedOrdering:
    def test_seed_table_call_order_commit_last(
        self, monkeypatch, recorder, machines_inferred, boundary, make_settings
    ):
        _wire_seed(monkeypatch, recorder, boundary, make_settings)
        result = full_seed.seed_table(
            SimpleNamespace(),
            machines_inferred,
            boundary,
            "run_1",
            use_flashback=True,
        )
        assert result["rows"] == 4
        recorder.assert_order(
            "extract",
            "stage_write",
            "stage_validate",
            "publish",
            "warehouse_load",
            "reconcile",
            "commit_watermark",
        )
        after_commit = recorder.calls[recorder.index("commit_watermark") + 1 :]
        assert after_commit == ["record_table_run:succeeded"]

    @pytest.mark.parametrize(
        "failure_stage",
        ["extract", "stage_write", "stage_validate", "publish", "warehouse_load"],
    )
    def test_seed_watermark_never_commits_on_failure(
        self,
        monkeypatch,
        recorder,
        machines_inferred,
        boundary,
        make_settings,
        failure_stage,
    ):
        _wire_seed(monkeypatch, recorder, boundary, make_settings)
        recorder.fail_at = failure_stage
        with pytest.raises(RuntimeError, match="injected failure"):
            full_seed.seed_table(
                SimpleNamespace(),
                machines_inferred,
                boundary,
                "run_1",
                use_flashback=False,
            )
        assert "commit_watermark" not in recorder.calls

    def test_seed_reconciliation_failure_blocks_watermark(
        self, monkeypatch, recorder, machines_inferred, boundary, make_settings
    ):
        _wire_seed(
            monkeypatch, recorder, boundary, make_settings, reconcile_passed=False
        )
        with pytest.raises(RuntimeError, match="Seed reconciliation failed"):
            full_seed.seed_table(
                SimpleNamespace(),
                machines_inferred,
                boundary,
                "run_1",
                use_flashback=True,
            )
        assert "commit_watermark" not in recorder.calls
        assert "record_table_run:failed" in recorder.calls


class TestRunFullSeed:
    def test_verifies_read_only_then_seeds_and_isolates_failures(
        self,
        monkeypatch,
        recorder,
        machines_inferred,
        boundary,
        make_settings,
        registry,
    ):
        _wire_seed(monkeypatch, recorder, boundary, make_settings)

        @contextmanager
        def fake_oracle_connection():
            yield SimpleNamespace(name="fake-oracle")

        monkeypatch.setattr(full_seed, "oracle_connection", fake_oracle_connection)
        monkeypatch.setattr(
            full_seed,
            "verify_read_only",
            lambda conn: (
                recorder.hit("verify_read_only")
                or {"session_privileges": ["CREATE SESSION"]}
            ),
        )
        monkeypatch.setattr(
            full_seed,
            "capture_boundary",
            lambda conn: recorder.hit("capture_boundary") or boundary,
        )
        monkeypatch.setattr(
            full_seed,
            "supports_flashback",
            lambda conn, table: recorder.hit("supports_flashback") or True,
        )
        monkeypatch.setattr(state, "new_run_id", lambda: "run_seed")
        monkeypatch.setattr(state, "start_run", lambda *a, **k: None)
        statuses: list[str] = []
        monkeypatch.setattr(
            state,
            "finish_run",
            lambda run_id, status, detail=None: statuses.append(status),
        )
        monkeypatch.setattr(
            full_seed, "refresh_catalog", lambda reg: recorder.hit("refresh_catalog")
        )

        suppliers_inferred = build_inferred(registry.get("OMEGA.SUPPLIERS"))
        plan = SimpleNamespace(
            plan_id="plan_x", tables=[machines_inferred, suppliers_inferred]
        )

        seeded: list[str] = []
        original_seed_table = full_seed.seed_table

        def selective_seed(conn, inferred, bnd, run_id, *, use_flashback):
            if inferred.contract.source_table == "SUPPLIERS":
                raise RuntimeError("boom on suppliers")
            seeded.append(inferred.contract.qualified_name)
            return original_seed_table(
                conn, inferred, bnd, run_id, use_flashback=use_flashback
            )

        monkeypatch.setattr(full_seed, "seed_table", selective_seed)
        result = full_seed.run_full_seed(plan, registry=registry)

        # Read-only proof strictly before any boundary capture or extraction.
        recorder.assert_order("verify_read_only", "capture_boundary", "extract")
        assert seeded == ["OMEGA.MACHINES"]
        assert result["status"] == "failed"
        assert result["failures"] == [
            {"table": "OMEGA.SUPPLIERS", "error": "boom on suppliers"}
        ]
        assert len(result["seeded"]) == 1
        assert statuses == ["failed"]
        # Catalog still refreshed so the healthy table is queryable.
        assert "refresh_catalog" in recorder.calls
