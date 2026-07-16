"""Watermark / control-state logic with a mocked warehouse engine."""

from __future__ import annotations

import zlib

import pytest

from app.dataplatform.pipeline import state
from tests_dataplatform.conftest import FakeEngine, FakeResult


@pytest.fixture
def fake_engine(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(state, "loader_engine", lambda: engine)
    return engine


class TestAdvisoryLock:
    def test_lock_key_derivation_is_stable_crc32(self):
        captured: list = []

        class Conn:
            def execute(self, statement, params=None):
                captured.append((str(statement), params))
                return FakeResult(scalar=True)

        assert state.acquire_pipeline_lock(Conn()) is True
        assert state.acquire_pipeline_lock(Conn(), "smartforge_pipeline") is True
        expected_key = zlib.crc32(b"smartforge_pipeline") % (2**31)
        for sql, params in captured:
            assert "pg_try_advisory_lock" in sql
            assert params == {"key": expected_key}
        # Same name -> same key on every call (unlike PYTHONHASHSEED hash()).
        assert captured[0][1] == captured[1][1]

    def test_lock_denied_returns_false(self):
        class Conn:
            def execute(self, statement, params=None):
                return FakeResult(scalar=False)

        assert state.acquire_pipeline_lock(Conn()) is False

    def test_different_names_use_different_keys(self):
        keys: list[int] = []

        class Conn:
            def execute(self, statement, params=None):
                keys.append(params["key"])
                return FakeResult(scalar=True)

        state.acquire_pipeline_lock(Conn(), "a")
        state.acquire_pipeline_lock(Conn(), "b")
        assert keys[0] != keys[1]


class TestWatermarks:
    def test_get_watermark_missing_row(self, fake_engine, machines_contract):
        watermark = state.get_watermark(machines_contract)
        assert watermark == state.Watermark(None, None, None, None)

    def test_get_watermark_parses_row(self, monkeypatch, machines_contract):
        def responder(sql, _params):
            if "replication_watermarks" in sql:
                return FakeResult(one=("2026-07-14T00:00:00", 4999, "load_a", None))
            return None

        engine = FakeEngine(responder)
        monkeypatch.setattr(state, "loader_engine", lambda: engine)
        watermark = state.get_watermark(machines_contract)
        assert watermark.cursor_value == "2026-07-14T00:00:00"
        assert watermark.source_scn == 4999
        assert watermark.load_id == "load_a"

    def test_commit_watermark_upserts_with_bound_values(
        self, fake_engine, machines_contract
    ):
        state.commit_watermark(
            machines_contract,
            cursor_value="2026-07-15T09:00:00",
            source_scn=5000,
            load_id="load_b",
        )
        assert len(fake_engine.connection.calls) == 1
        sql, params = fake_engine.connection.calls[0]
        assert "INSERT INTO control.replication_watermarks" in sql
        assert "ON CONFLICT (source_schema, source_table) DO UPDATE" in sql
        assert params == {
            "schema": "OMEGA",
            "table": "MACHINES",
            "cursor_column": "LAST_UPDATE_TS",
            "cursor_value": "2026-07-15T09:00:00",
            "scn": 5000,
            "load_id": "load_b",
        }
        # Values travel as binds, never interpolated into SQL text.
        assert "load_b" not in sql and "5000" not in sql

    def test_commit_not_called_means_no_statement(self, fake_engine):
        # Sanity for the ordering tests: nothing touches the engine unless
        # commit_watermark is actually invoked.
        assert fake_engine.connection.calls == []


class TestSchemaDrift:
    def _engine(self, monkeypatch, *, known_count: int, insert_returns_row: bool):
        def responder(sql, params):
            if "SELECT count(*)" in sql:
                return FakeResult(scalar=known_count)
            if "INSERT INTO control.schema_versions" in sql:
                one = (params["hash"],) if insert_returns_row else None
                return FakeResult(one=one)
            return None

        engine = FakeEngine(responder)
        monkeypatch.setattr(state, "loader_engine", lambda: engine)
        return engine

    def test_first_observation_is_not_drift(self, monkeypatch, machines_contract):
        self._engine(monkeypatch, known_count=0, insert_returns_row=True)
        assert state.record_schema_version(machines_contract, "sha256:aaa", []) is False

    def test_same_hash_again_is_not_drift(self, monkeypatch, machines_contract):
        # ON CONFLICT DO NOTHING -> RETURNING yields no row for a known hash.
        self._engine(monkeypatch, known_count=1, insert_returns_row=False)
        assert state.record_schema_version(machines_contract, "sha256:aaa", []) is False

    def test_new_hash_with_prior_history_is_drift(self, monkeypatch, machines_contract):
        self._engine(monkeypatch, known_count=1, insert_returns_row=True)
        assert state.record_schema_version(machines_contract, "sha256:bbb", []) is True


class TestRunRecords:
    def test_new_run_id_is_unique_and_sortable(self):
        a, b = state.new_run_id(), state.new_run_id()
        assert a != b
        assert len(a.split("_")) == 2

    def test_start_and_finish_run_statements(self, fake_engine):
        state.start_run("r1", "incremental", {"cadences": ["hourly"]})
        state.finish_run("r1", "succeeded", {"synced": 1})
        sql_start, params_start = fake_engine.connection.calls[0]
        sql_finish, params_finish = fake_engine.connection.calls[1]
        assert "INSERT INTO control.replication_runs" in sql_start
        assert params_start["run_id"] == "r1"
        assert params_start["kind"] == "incremental"
        assert "UPDATE control.replication_runs" in sql_finish
        assert params_finish["status"] == "succeeded"

    def test_record_table_run_binds_contract_fields(
        self, fake_engine, machines_contract
    ):
        state.record_table_run(
            "r1",
            "load_x",
            machines_contract,
            status="extracting",
            source_scn=5000,
        )
        sql, params = fake_engine.connection.calls[0]
        assert "INSERT INTO control.replication_table_runs" in sql
        assert params["schema"] == "OMEGA"
        assert params["table"] == "MACHINES"
        assert params["strategy"] == "updated_at_merge"
        assert params["status"] == "extracting"
        assert params["scn"] == 5000
