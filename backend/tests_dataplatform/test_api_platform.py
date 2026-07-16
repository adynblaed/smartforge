"""/platform endpoints: RBAC gates, health shape, seed-confirm flow."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import app.api.routes.platform as platform_routes
from app.dataplatform.pipeline import plans, state
from tests_dataplatform.conftest import FakeEngine, FakeResult, assert_clean_error_body


@pytest.fixture(autouse=True)
def _stub_pipeline_lock(monkeypatch):
    """seed/confirm and sync/run take the single-flight lock (INC-013);
    offline tests stub it — test_single_flight.py proves the guard."""

    @contextmanager
    def fake_lock(name: str = "smartforge_pipeline"):  # noqa: ARG001
        yield

    monkeypatch.setattr(state, "pipeline_lock", fake_lock)


@pytest.fixture
def healthy_engine(monkeypatch, platform_env):  # noqa: ARG001
    engine = FakeEngine(lambda sql, params: FakeResult(scalar=1))
    monkeypatch.setattr(platform_routes, "api_engine", lambda: engine)
    return engine


@pytest.fixture
def dead_engine(monkeypatch, platform_env):  # noqa: ARG001
    engine = FakeEngine(fail_connect=True)
    monkeypatch.setattr(platform_routes, "api_engine", lambda: engine)
    return engine


class TestAuth:
    def test_unauthenticated_rejected_everywhere(self, anon_client, platform_env):
        assert anon_client.get("/api/v1/platform/health").status_code == 401
        assert anon_client.post("/api/v1/platform/discovery/run").status_code == 401
        assert (
            anon_client.post("/api/v1/platform/seed/confirm", json={}).status_code
            == 401
        )
        assert anon_client.post("/api/v1/platform/sync/run", json={}).status_code == 401

    @pytest.mark.parametrize(
        ("method", "url", "body"),
        [
            ("post", "/api/v1/platform/discovery/run", None),
            (
                "post",
                "/api/v1/platform/seed/confirm",
                {
                    "plan_id": "p",
                    "fingerprint": "f",
                    "confirmation_phrase": "SEED OMEGA",
                },
            ),
            ("post", "/api/v1/platform/sync/run", {"cadences": ["hourly"]}),
        ],
    )
    def test_mutating_endpoints_require_superuser(
        self, internal_client, platform_env, method, url, body
    ):
        response = getattr(internal_client, method)(url, json=body)
        assert response.status_code == 403
        assert "privileges" in response.json()["detail"]

    def test_read_endpoints_allow_internal_users(self, internal_client, healthy_engine):
        assert internal_client.get("/api/v1/platform/health").status_code == 200


class TestHealth:
    def test_health_shape_with_warehouse_up(
        self, internal_client, healthy_engine, platform_env
    ):
        body = internal_client.get("/api/v1/platform/health").json()
        assert set(body) == {
            "warehouse",
            "duckdb_catalog",
            "lake_root",
            "lake_published",
            "environment",
        }
        assert body["warehouse"] == "ok"
        assert body["duckdb_catalog"] == "missing"  # tmp catalog not built
        assert body["lake_published"] is False
        assert body["environment"] == "development"

    def test_health_degrades_when_warehouse_down(self, internal_client, dead_engine):
        body = internal_client.get("/api/v1/platform/health").json()
        assert body["warehouse"] == "unavailable"

    def test_health_reports_catalog_when_present(
        self, internal_client, healthy_engine, platform_env
    ):
        platform_env.DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
        platform_env.DUCKDB_PATH.write_bytes(b"")
        platform_env.lake_published_dir.mkdir(parents=True, exist_ok=True)
        body = internal_client.get("/api/v1/platform/health").json()
        assert body["duckdb_catalog"] == "ok"
        assert body["lake_published"] is True


class TestObservabilityEndpoints:
    def test_replication_runs_503_when_warehouse_down(
        self, internal_client, dead_engine
    ):
        response = internal_client.get("/api/v1/platform/replication/runs")
        assert response.status_code == 503
        assert_clean_error_body(response.json())

    def test_freshness_aggregates_worst_status(
        self, monkeypatch, internal_client, platform_env
    ):
        report = [
            {"table": "OMEGA.A", "status": "fresh"},
            {"table": "OMEGA.B", "status": "warning"},
        ]
        monkeypatch.setattr(platform_routes, "table_freshness", lambda: report)
        body = internal_client.get("/api/v1/platform/freshness").json()
        assert body["overall"] == "warning"

        report.append({"table": "OMEGA.C", "status": "never_loaded"})
        body = internal_client.get("/api/v1/platform/freshness").json()
        assert body["overall"] == "stale"

    def test_replication_tables_joins_contracts_and_freshness(
        self, monkeypatch, internal_client, platform_env
    ):
        monkeypatch.setattr(
            platform_routes,
            "table_freshness",
            lambda registry: [
                {
                    "table": "OMEGA.MACHINES",
                    "status": "fresh",
                    "lag_minutes": 3.0,
                    "last_load_id": "load_z",
                    "last_published_at": "2026-07-15T09:00:00+00:00",
                    "source_scn": 5000,
                }
            ],
        )
        body = internal_client.get("/api/v1/platform/replication/tables").json()
        assert body["count"] >= 12
        machines = next(t for t in body["data"] if t["table"] == "OMEGA.MACHINES")
        assert machines["status"] == "fresh"
        assert machines["last_load_id"] == "load_z"
        assert machines["strategy"] == "updated_at_merge"
        assert machines["cursor_column"] == "LAST_UPDATE_TS"


class TestDiscovery:
    def test_discovery_returns_plan_summary(
        self, monkeypatch, superuser_client, platform_env
    ):
        fake_plan = SimpleNamespace(
            plan_id="plan_1",
            fingerprint=lambda: "abcd1234",
            is_seedable=True,
            blocking_issues=[],
            tables=[1, 2, 3],
        )
        monkeypatch.setattr(plans, "discover", lambda: fake_plan)
        response = superuser_client.post("/api/v1/platform/discovery/run")
        assert response.status_code == 200
        assert response.json() == {
            "plan_id": "plan_1",
            "fingerprint": "abcd1234",
            "seedable": True,
            "blocking_issues": [],
            "table_count": 3,
        }

    def test_discovery_failure_is_opaque(
        self, monkeypatch, superuser_client, platform_env
    ):
        def exploding_discover():
            raise RuntimeError(
                "ORA-12170: SELECT * FROM all_tab_columns at oracle.internal:1521 "
                "C:\\secret\\wallet"
            )

        monkeypatch.setattr(plans, "discover", exploding_discover)
        response = superuser_client.post("/api/v1/platform/discovery/run")
        assert response.status_code == 502
        detail = response.json()["detail"]
        # Only the exception *type* leaks, never the message/SQL/path.
        assert detail == "Omega discovery failed: RuntimeError"
        assert_clean_error_body(response.json())

    def test_read_only_violation_maps_to_409(
        self, monkeypatch, superuser_client, platform_env
    ):
        def refusing_discover():
            raise PermissionError("write privileges found; refusing to run")

        monkeypatch.setattr(plans, "discover", refusing_discover)
        response = superuser_client.post("/api/v1/platform/discovery/run")
        assert response.status_code == 409


class TestSeedConfirm:
    BODY = {
        "plan_id": "plan_1",
        "fingerprint": "abcd1234",
        "confirmation_phrase": "SEED WRONG",
        "tables": ["OMEGA.MACHINES"],
    }

    def test_wrong_phrase_rejected_409(
        self, monkeypatch, superuser_client, platform_env
    ):
        def failing_confirm(*_args, **_kwargs):
            raise plans.PlanNotConfirmedError(
                "Confirmation phrase mismatch. Type 'SEED OMEGA' to authorize seeding."
            )

        monkeypatch.setattr(plans, "confirm_plan", failing_confirm)
        response = superuser_client.post(
            "/api/v1/platform/seed/confirm", json=self.BODY
        )
        assert response.status_code == 409
        assert "phrase mismatch" in response.json()["detail"]
        assert_clean_error_body(response.json())

    def test_confirmed_plan_starts_background_seed(
        self, monkeypatch, superuser_client, platform_env
    ):
        fake_plan = SimpleNamespace(plan_id="plan_1", tables=[])
        monkeypatch.setattr(
            plans,
            "confirm_plan",
            lambda plan_id, fingerprint, phrase, confirmed_by: fake_plan,
        )
        executed: list[tuple] = []
        import app.dataplatform.pipeline.full_seed as full_seed_module

        monkeypatch.setattr(
            full_seed_module,
            "run_full_seed",
            lambda plan, tables=None: (
                executed.append(("seed", plan.plan_id, tables))
                or {"status": "succeeded"}
            ),
        )
        monkeypatch.setattr(
            plans,
            "mark_executed",
            lambda plan_id, result: executed.append(("mark", plan_id)),
        )
        body = dict(self.BODY, confirmation_phrase="SEED OMEGA")
        response = superuser_client.post("/api/v1/platform/seed/confirm", json=body)
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "seeding_started"
        assert payload["plan_id"] == "plan_1"
        assert payload["tables"] == ["OMEGA.MACHINES"]
        # TestClient runs background tasks before returning: the seed ran.
        assert ("seed", "plan_1", ["OMEGA.MACHINES"]) in executed
        assert ("mark", "plan_1") in executed

    def test_seed_plan_404_when_none_proposed(
        self, monkeypatch, internal_client, platform_env
    ):
        monkeypatch.setattr(plans, "latest_plan", lambda: None)
        response = internal_client.get("/api/v1/platform/seed/plan")
        assert response.status_code == 404


class TestSyncRun:
    def test_sync_runs_in_background_for_superuser(
        self, monkeypatch, superuser_client, platform_env
    ):
        import app.dataplatform.pipeline.incremental as incremental_module

        calls: list[tuple] = []
        monkeypatch.setattr(
            incremental_module,
            "run_incremental",
            lambda cadences, tables=None: (
                calls.append((cadences, tables))
                or {"run_id": "r", "synced": [], "failures": []}
            ),
        )
        response = superuser_client.post(
            "/api/v1/platform/sync/run",
            json={"cadences": ["hourly"], "tables": ["OMEGA.MACHINES"]},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "sync_started"
        assert calls == [(["hourly"], ["OMEGA.MACHINES"])]
