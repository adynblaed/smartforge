"""Warehouse loader guards with a mocked engine (no dlt run, no Postgres)."""

from __future__ import annotations

import pytest

from app.dataplatform.warehouse import loader
from tests_dataplatform.conftest import (
    FakeEngine,
    FakeResult,
    build_inferred,
    make_boundary,
)
from tests_dataplatform.test_lake_parquet import make_manifest


def _manifest_for(machines_contract, scn: int):
    inferred = build_inferred(machines_contract)
    return make_manifest(inferred, make_boundary(scn), rows=10)


class TestAssertLoadOrder:
    def _engine(self, monkeypatch, newest_loaded_scn):
        def responder(sql, _params):
            if "max(source_scn)" in sql:
                return FakeResult(scalar=newest_loaded_scn)
            return None

        engine = FakeEngine(responder)
        monkeypatch.setattr(loader, "loader_engine", lambda: engine)
        return engine

    def test_refuses_load_older_than_newest_loaded(
        self, monkeypatch, machines_contract
    ):
        self._engine(monkeypatch, newest_loaded_scn=5000)
        manifest = _manifest_for(machines_contract, scn=4000)
        with pytest.raises(loader.LoadOrderError, match="INC-006"):
            loader.assert_load_order(machines_contract, manifest)

    def test_accepts_newer_load(self, monkeypatch, machines_contract):
        self._engine(monkeypatch, newest_loaded_scn=5000)
        loader.assert_load_order(
            machines_contract, _manifest_for(machines_contract, 6000)
        )

    def test_accepts_replay_of_the_newest_load(self, monkeypatch, machines_contract):
        # Replaying the newest applied load is idempotent and allowed.
        self._engine(monkeypatch, newest_loaded_scn=5000)
        loader.assert_load_order(
            machines_contract, _manifest_for(machines_contract, 5000)
        )

    def test_accepts_first_ever_load(self, monkeypatch, machines_contract):
        self._engine(monkeypatch, newest_loaded_scn=None)
        loader.assert_load_order(machines_contract, _manifest_for(machines_contract, 1))

    def test_queries_only_loaded_manifests_with_binds(
        self, monkeypatch, machines_contract
    ):
        engine = self._engine(monkeypatch, newest_loaded_scn=None)
        loader.assert_load_order(machines_contract, _manifest_for(machines_contract, 1))
        sql, params = engine.connection.calls[0]
        assert "status = 'loaded'" in sql
        assert params == {"schema": "OMEGA", "table": "MACHINES"}


class TestMarkDeletedKeys:
    def _engine(self, monkeypatch, warehouse_keys):
        def responder(sql, _params):
            if sql.strip().startswith("SELECT"):
                return FakeResult(rows=warehouse_keys)
            return None

        engine = FakeEngine(responder)
        monkeypatch.setattr(loader, "loader_engine", lambda: engine)
        return engine

    def test_marks_vanished_keys_with_parameterized_updates(
        self, monkeypatch, machines_contract
    ):
        engine = self._engine(monkeypatch, warehouse_keys=[(1,), (2,), (3,)])
        marked = loader.mark_deleted_keys(machines_contract, source_keys={(2,)})
        assert marked == 2

        select_sql, _ = engine.connection.calls[0]
        assert 'SELECT "machine_id" FROM raw_oracle."machines"' in select_sql
        assert "WHERE NOT coalesce(_is_deleted, false)" in select_sql

        updates = engine.connection.calls[1:]
        assert len(updates) == 2
        marked_keys = set()
        for sql, params in updates:
            assert 'UPDATE raw_oracle."machines"' in sql
            assert "SET _is_deleted = true" in sql
            assert '"machine_id" = :k0' in sql
            # Values are bound, never inlined into the statement.
            assert str(params["k0"]) not in sql
            marked_keys.add(params["k0"])
        assert marked_keys == {1, 3}

    def test_no_updates_when_source_has_all_keys(self, monkeypatch, machines_contract):
        engine = self._engine(monkeypatch, warehouse_keys=[(1,), (2,)])
        marked = loader.mark_deleted_keys(machines_contract, source_keys={(1,), (2,)})
        assert marked == 0
        assert len(engine.connection.calls) == 1  # only the SELECT

    def test_composite_key_predicate(self, monkeypatch, registry):
        contract = registry.get("OMEGA.PURCHASE_ORDER_LINES")
        engine = self._engine(monkeypatch, warehouse_keys=[(10, 1), (10, 2)])
        marked = loader.mark_deleted_keys(contract, source_keys={(10, 1)})
        assert marked == 1
        sql, params = engine.connection.calls[1]
        assert '"po_id" = :k0 AND "line_number" = :k1' in sql
        assert params == {"k0": 10, "k1": 2}
