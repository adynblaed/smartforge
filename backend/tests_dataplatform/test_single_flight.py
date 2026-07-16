"""Pipeline single-flight enforcement on EVERY writer entry point (INC-013)
and bootstrap DDL quoting (SEC-001): the corrections register for the
engine-separation review findings."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import app.api.routes.platform as platform_routes
from app.dataplatform.pipeline import state
from app.dataplatform.warehouse import postgres as warehouse_postgres
from tests_dataplatform.conftest import FakeEngine, FakeResult


class TestPipelineLock:
    @pytest.fixture
    def lock_engine(self, monkeypatch):
        def responder(sql, _params):
            if "pg_try_advisory_lock" in sql:
                return FakeResult(scalar=True)
            return None

        engine = FakeEngine(responder)
        monkeypatch.setattr(state, "loader_engine", lambda: engine)
        return engine

    def test_acquires_runs_and_releases(self, lock_engine):
        ran: list[bool] = []
        with state.pipeline_lock():
            ran.append(True)
        statements = lock_engine.connection.statements()
        assert ran == [True]
        acquire_idx = next(
            i for i, s in enumerate(statements) if "pg_try_advisory_lock" in s
        )
        release_idx = next(
            i for i, s in enumerate(statements) if "pg_advisory_unlock" in s
        )
        assert acquire_idx < release_idx

    def test_releases_even_when_the_body_raises(self, lock_engine):
        with pytest.raises(RuntimeError, match="boom"):
            with state.pipeline_lock():
                raise RuntimeError("boom")
        assert any(
            "pg_advisory_unlock" in s for s in lock_engine.connection.statements()
        )

    def test_busy_raises_and_never_runs_the_body(self, monkeypatch):
        engine = FakeEngine(
            lambda sql, _p: (
                FakeResult(scalar=False) if "pg_try_advisory_lock" in sql else None
            )
        )
        monkeypatch.setattr(state, "loader_engine", lambda: engine)
        with pytest.raises(state.PipelineBusyError):
            with state.pipeline_lock():
                pytest.fail("body must not run while the lock is held elsewhere")
        # No unlock: this session never owned the lock.
        assert not any(
            "pg_advisory_unlock" in s for s in engine.connection.statements()
        )


class TestApiSingleFlight:
    """POST /platform/sync/run and /seed/confirm can never overlap a
    running pipeline: 409 up front, hard lock in the background task."""

    @pytest.fixture
    def busy_lock(self, monkeypatch):
        @contextmanager
        def busy(name: str = "smartforge_pipeline"):  # noqa: ARG001
            raise state.PipelineBusyError("another pipeline run holds the lock")
            yield  # pragma: no cover

        monkeypatch.setattr(state, "pipeline_lock", busy)

    @pytest.fixture
    def free_lock(self, monkeypatch):
        calls: list[str] = []

        @contextmanager
        def free(name: str = "smartforge_pipeline"):  # noqa: ARG001
            calls.append("acquired")
            yield
            calls.append("released")

        monkeypatch.setattr(state, "pipeline_lock", free)
        return calls

    def test_sync_run_409_when_pipeline_busy(self, superuser_client, busy_lock):
        response = superuser_client.post(
            "/api/v1/platform/sync/run", json={"cadences": ["hourly"]}
        )
        assert response.status_code == 409
        assert "lock" in response.json()["detail"]

    def test_seed_confirm_409_when_pipeline_busy(
        self, monkeypatch, superuser_client, busy_lock
    ):
        monkeypatch.setattr(
            platform_routes.seed_plans,
            "confirm_plan",
            lambda *a, **k: SimpleNamespace(plan_id="plan_x", tables=[]),
        )
        response = superuser_client.post(
            "/api/v1/platform/seed/confirm",
            json={
                "plan_id": "plan_x",
                "fingerprint": "f",
                "confirmation_phrase": "SEED OMEGA",
                "tables": ["OMEGA.MACHINES"],
            },
        )
        assert response.status_code == 409

    def test_sync_run_executes_inside_the_lock(
        self, monkeypatch, superuser_client, free_lock
    ):
        import app.dataplatform.pipeline.incremental as incremental_module

        def fake_run(cadences, tables=None):  # noqa: ARG001
            # The probe acquired+released once; the background task must be
            # INSIDE its own acquisition when the pipeline actually runs.
            free_lock.append("ran")
            return {"run_id": "r", "synced": [], "failures": []}

        monkeypatch.setattr(incremental_module, "run_incremental", fake_run)
        response = superuser_client.post(
            "/api/v1/platform/sync/run", json={"cadences": ["hourly"]}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "sync_started"
        # probe acquire/release, then task acquire -> run -> release
        assert free_lock == [
            "acquired",
            "released",
            "acquired",
            "ran",
            "released",
        ]

    def test_sync_run_requires_superuser(self, internal_client, free_lock):
        response = internal_client.post(
            "/api/v1/platform/sync/run", json={"cadences": ["hourly"]}
        )
        assert response.status_code == 403
        assert free_lock == []  # nothing probed, nothing run


class TestBootstrapQuoting:
    """Role provisioning DDL is injection-safe (SEC-001): identifiers are
    allowlisted and secrets are quote-doubled outside any dollar-quoting."""

    def test_password_with_quotes_and_dollars_is_contained(self, make_settings):
        settings = make_settings(
            WAREHOUSE_LOADER_PASSWORD="it's $$ tricky'; DROP ROLE x; --",
        )
        statements = warehouse_postgres._role_statements(settings)
        alters = [s for s in statements if s.startswith("ALTER ROLE")]
        assert alters, "expected top-level ALTER ROLE statements"
        loader_alter = alters[0]
        # Quote-doubled literal: the raw single quote never terminates it.
        assert "it''s $$ tricky''; DROP ROLE x; --" in loader_alter
        # And no secret ever sits inside a dollar-quoted DO block.
        for statement in statements:
            if "DO $$" in statement:
                assert "tricky" not in statement

    def test_unsafe_role_name_fails_closed(self, make_settings):
        settings = make_settings(WAREHOUSE_DBT_USER='dbt"; DROP ROLE admin; --')
        with pytest.raises(ValueError, match="Unsafe PostgreSQL identifier"):
            warehouse_postgres._role_statements(settings)

    def test_unsafe_database_name_fails_closed(self, make_settings):
        settings = make_settings(WAREHOUSE_DB='w"h')
        with pytest.raises(ValueError, match="Unsafe PostgreSQL identifier"):
            warehouse_postgres._role_statements(settings)
