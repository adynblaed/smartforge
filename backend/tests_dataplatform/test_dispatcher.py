"""Cadence dispatcher: due windows, single-flight lock, dbt gating,
post-tick lake maintenance (LAKE-011)."""

from __future__ import annotations

import datetime as dt
import logging
import os
import subprocess
import time

import pytest

from app.dataplatform.pipeline import dispatcher, state
from tests_dataplatform.conftest import FakeEngine


def utc(year=2026, month=7, day=15, hour=12, minute=0):
    return dt.datetime(year, month, day, hour, minute, tzinfo=dt.timezone.utc)


class TestDueCadences:
    def test_hourly_always_due(self):
        assert dispatcher.due_cadences(utc(hour=13)) == ["hourly"]
        assert dispatcher.due_cadences(utc(hour=0)) == ["hourly"]

    def test_daily_due_only_at_0200_utc(self):
        assert dispatcher.due_cadences(utc(hour=2)) == ["hourly", "daily"]
        assert "daily" not in dispatcher.due_cadences(utc(hour=1))
        assert "daily" not in dispatcher.due_cadences(utc(hour=3))

    def test_weekly_due_only_sunday_0300_utc(self):
        sunday = dt.datetime(2026, 7, 19, 3, 0, tzinfo=dt.timezone.utc)
        assert sunday.weekday() == 6
        assert dispatcher.due_cadences(sunday) == ["hourly", "weekly"]
        # Same hour on a Wednesday: not due.
        wednesday = utc(day=15, hour=3)
        assert wednesday.weekday() == 2
        assert dispatcher.due_cadences(wednesday) == ["hourly"]
        # Sunday at a different hour: not due.
        sunday_2am = sunday.replace(hour=2)
        assert dispatcher.due_cadences(sunday_2am) == ["hourly", "daily"]


class TestDispatchLocking:
    def test_skips_tick_when_lock_held(self, monkeypatch, registry):
        engine = FakeEngine()
        monkeypatch.setattr(dispatcher, "loader_engine", lambda: engine)
        monkeypatch.setattr(dispatcher, "load_registry", lambda: registry)
        monkeypatch.setattr(
            state, "acquire_pipeline_lock", lambda conn, name="x": False
        )

        called: list[str] = []
        monkeypatch.setattr(
            dispatcher,
            "run_incremental",
            lambda *a, **k: called.append("sync") or {"synced": [], "failures": []},
        )
        result = dispatcher.dispatch(cadences=["hourly"], with_dbt=False)
        assert result == {"status": "skipped", "reason": "pipeline lock held"}
        assert called == []  # nothing ran under a held lock

    def test_runs_sync_when_lock_acquired(self, monkeypatch, registry):
        engine = FakeEngine()
        monkeypatch.setattr(dispatcher, "loader_engine", lambda: engine)
        monkeypatch.setattr(dispatcher, "load_registry", lambda: registry)
        monkeypatch.setattr(state, "acquire_pipeline_lock", lambda conn, name="x": True)
        monkeypatch.setattr(
            dispatcher,
            "run_incremental",
            lambda cadences, registry: {"synced": [{"table": "T"}], "failures": []},
        )
        result = dispatcher.dispatch(cadences=["hourly"], with_dbt=False)
        assert result["status"] == "succeeded"
        assert result["sync"]["synced"] == [{"table": "T"}]
        assert "delete_reconciliation" not in result

    def test_weekly_tick_runs_delete_reconciliation(self, monkeypatch, registry):
        engine = FakeEngine()
        monkeypatch.setattr(dispatcher, "loader_engine", lambda: engine)
        monkeypatch.setattr(dispatcher, "load_registry", lambda: registry)
        monkeypatch.setattr(state, "acquire_pipeline_lock", lambda conn, name="x": True)
        monkeypatch.setattr(
            dispatcher,
            "run_incremental",
            lambda cadences, registry: {"synced": [], "failures": []},
        )
        recon_calls: list = []
        monkeypatch.setattr(
            dispatcher,
            "run_delete_reconciliation",
            lambda **k: recon_calls.append(k) or {"reconciled": [], "failures": []},
        )
        result = dispatcher.dispatch(cadences=["hourly", "weekly"], with_dbt=False)
        assert len(recon_calls) == 1
        assert result["delete_reconciliation"] == {"reconciled": [], "failures": []}

    def test_dbt_failure_yields_partial_status(self, monkeypatch, registry):
        engine = FakeEngine()
        monkeypatch.setattr(dispatcher, "loader_engine", lambda: engine)
        monkeypatch.setattr(dispatcher, "load_registry", lambda: registry)
        monkeypatch.setattr(state, "acquire_pipeline_lock", lambda conn, name="x": True)
        monkeypatch.setattr(
            dispatcher,
            "run_incremental",
            lambda cadences, registry: {"synced": [{"table": "T"}], "failures": []},
        )

        def failing_dbt(_targets=None):
            raise RuntimeError("dbt build failed for target warehouse")

        monkeypatch.setattr(dispatcher, "run_dbt", failing_dbt)
        result = dispatcher.dispatch(cadences=["hourly"], with_dbt=True)
        assert result["status"] == "partial"
        assert "dbt build failed" in result["dbt"]["error"]

    def test_dbt_skipped_when_nothing_synced(self, monkeypatch, registry):
        engine = FakeEngine()
        monkeypatch.setattr(dispatcher, "loader_engine", lambda: engine)
        monkeypatch.setattr(dispatcher, "load_registry", lambda: registry)
        monkeypatch.setattr(state, "acquire_pipeline_lock", lambda conn, name="x": True)
        monkeypatch.setattr(
            dispatcher,
            "run_incremental",
            lambda cadences, registry: {"synced": [], "failures": []},
        )

        def exploding_dbt(_targets=None):  # pragma: no cover - must not run
            raise AssertionError("dbt must not run when nothing synced")

        monkeypatch.setattr(dispatcher, "run_dbt", exploding_dbt)
        result = dispatcher.dispatch(cadences=["hourly"], with_dbt=True)
        assert result["status"] == "succeeded"
        assert "dbt" not in result


class TestLakeMaintenance:
    """LAKE-011: retention runs on the production path, never fails a tick."""

    def _wire_dispatch(self, monkeypatch, registry, *, lock: bool = True):
        engine = FakeEngine()
        monkeypatch.setattr(dispatcher, "loader_engine", lambda: engine)
        monkeypatch.setattr(dispatcher, "load_registry", lambda: registry)
        monkeypatch.setattr(state, "acquire_pipeline_lock", lambda conn, name="x": lock)
        monkeypatch.setattr(
            dispatcher,
            "run_incremental",
            lambda cadences, registry: {"synced": [], "failures": []},
        )

    def test_maintenance_runs_after_successful_tick(self, monkeypatch, registry):
        self._wire_dispatch(monkeypatch, registry)
        maintained: list = []
        monkeypatch.setattr(
            dispatcher,
            "lake_maintenance",
            lambda reg: maintained.append(reg) or {"snapshots_pruned": 0},
        )
        result = dispatcher.dispatch(cadences=["hourly"], with_dbt=False)
        assert result["status"] == "succeeded"
        assert result["lake_maintenance"] == {"snapshots_pruned": 0}
        assert maintained == [registry]

    def test_maintenance_never_runs_on_lock_skip(self, monkeypatch, registry):
        self._wire_dispatch(monkeypatch, registry, lock=False)
        monkeypatch.setattr(
            dispatcher,
            "lake_maintenance",
            lambda reg: pytest.fail("maintenance must not run on a skipped tick"),
        )
        result = dispatcher.dispatch(cadences=["hourly"], with_dbt=False)
        assert result == {"status": "skipped", "reason": "pipeline lock held"}

    def test_stale_staging_dir_quarantined_fresh_one_survives(
        self, platform_env, registry
    ):
        settings = platform_env
        stale = settings.lake_staging_dir / "load_id=20200101T000000Z_1" / "machines"
        stale.mkdir(parents=True)
        (stale / "part-00000.parquet").write_bytes(b"abandoned")
        fresh = settings.lake_staging_dir / "load_id=20990101T000000Z_2" / "machines"
        fresh.mkdir(parents=True)
        (fresh / "part-00000.parquet").write_bytes(b"in-flight")
        backdated = time.time() - settings.PIPELINE_LOCK_TTL_SECONDS - 3600
        for path in (stale / "part-00000.parquet", stale, stale.parent):
            os.utime(path, (backdated, backdated))

        result = dispatcher.lake_maintenance(registry)

        assert not stale.exists()
        quarantined = (
            settings.lake_quarantine_dir / "load_id=20200101T000000Z_1" / "machines"
        )
        assert (quarantined / "part-00000.parquet").exists()
        reason = (quarantined / "_quarantine_reason.txt").read_text(encoding="utf-8")
        assert "abandoned staging directory" in reason
        assert result["staging_quarantined"] == [str(quarantined)]
        # The fresh staging dir is untouched: a live run may still own it.
        assert (fresh / "part-00000.parquet").exists()

    def test_prune_called_with_configured_retention(
        self, monkeypatch, platform_env, registry
    ):
        settings = platform_env
        machines_dir = registry.get("OMEGA.MACHINES").lake_table_dir(
            settings.lake_published_dir
        )
        machines_dir.mkdir(parents=True)
        pruned: list[tuple] = []
        monkeypatch.setattr(
            dispatcher.lake_parquet,
            "prune_snapshots",
            lambda table_dir, retain: pruned.append((table_dir, retain)) or [],
        )
        dispatcher.lake_maintenance(registry)
        assert (machines_dir, settings.LAKE_RETAINED_SNAPSHOTS) in pruned
        # Only tables with a published tree are touched.
        assert all(table_dir.exists() for table_dir, _ in pruned)

    def test_prune_failure_logged_but_dispatch_result_unaffected(
        self, monkeypatch, platform_env, registry, caplog
    ):
        settings = platform_env
        machines_dir = registry.get("OMEGA.MACHINES").lake_table_dir(
            settings.lake_published_dir
        )
        machines_dir.mkdir(parents=True)
        self._wire_dispatch(monkeypatch, registry)

        def exploding_prune(_table_dir, _retain):
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(dispatcher.lake_parquet, "prune_snapshots", exploding_prune)
        with caplog.at_level(
            logging.WARNING, logger="app.dataplatform.pipeline.dispatcher"
        ):
            result = dispatcher.dispatch(cadences=["hourly"], with_dbt=False)
        assert result["status"] == "succeeded"
        assert result["lake_maintenance"]["warnings"] >= 1
        assert any(
            "snapshot pruning failed" in record.getMessage()
            for record in caplog.records
        )


class TestRunDbt:
    def _completed(self, returncode: int):
        return subprocess.CompletedProcess(
            args=["dbt"], returncode=returncode, stdout="log tail", stderr=""
        )

    def test_dbt_failure_raises_and_blocks(self, monkeypatch, platform_env):
        monkeypatch.setattr(
            dispatcher.subprocess, "run", lambda *a, **k: self._completed(1)
        )
        with pytest.raises(RuntimeError, match="dbt build failed for target warehouse"):
            dispatcher.run_dbt()

    def test_dbt_success_runs_both_targets(self, monkeypatch, platform_env):
        commands: list[list[str]] = []

        def record(cmd, **_kwargs):
            commands.append(cmd)
            return self._completed(0)

        monkeypatch.setattr(dispatcher.subprocess, "run", record)
        results = dispatcher.run_dbt()
        assert set(results) == {"warehouse", "lake"}
        assert all(r["returncode"] == 0 for r in results.values())
        targets = [cmd[cmd.index("--target") + 1] for cmd in commands]
        assert targets == ["warehouse", "lake"]
