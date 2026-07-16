"""/warehouse endpoints with a recording fake engine (no Postgres server)."""

from __future__ import annotations

import logging

import pytest

import app.api.routes.warehouse as warehouse_routes
from tests_dataplatform.conftest import FakeEngine, FakeResult, assert_clean_error_body

DATASET_COLUMNS = [
    ("marts", "fct_work_orders", "wo_id", "bigint"),
    ("marts", "fct_work_orders", "status", "text"),
    ("marts", "fct_work_orders", "due_at", "timestamp without time zone"),
    ("marts", "fct_work_orders", "qty_ordered", "numeric"),
    ("api", "v_kpis", "kpi", "text"),
]


@pytest.fixture
def fake_warehouse(monkeypatch, platform_env):  # noqa: ARG001
    def responder(sql, _params):
        if "information_schema.columns" in sql:
            return FakeResult(rows=DATASET_COLUMNS)
        if "count(*)" in sql:
            return FakeResult(scalar=1)
        if sql.strip().startswith("SELECT * FROM"):
            return FakeResult(mapping_rows=[{"wo_id": 1, "status": "open"}])
        return None

    engine = FakeEngine(responder)
    monkeypatch.setattr(warehouse_routes, "api_engine", lambda: engine)
    return engine


class TestAuth:
    def test_unauthenticated_rejected(self, anon_client, fake_warehouse):
        assert anon_client.get("/api/v1/warehouse/datasets").status_code == 401
        assert (
            anon_client.get(
                "/api/v1/warehouse/datasets/marts.fct_work_orders"
            ).status_code
            == 401
        )


class TestListDatasets:
    def test_allowlist_from_marts_and_api_schemas(
        self, internal_client, fake_warehouse
    ):
        response = internal_client.get("/api/v1/warehouse/datasets")
        assert response.status_code == 200
        body = response.json()
        datasets = {d["dataset"]: d for d in body["data"]}
        assert set(datasets) == {"marts.fct_work_orders", "api.v_kpis"}
        assert datasets["api.v_kpis"]["certified"] is True
        assert datasets["marts.fct_work_orders"]["certified"] is False
        assert datasets["marts.fct_work_orders"]["column_count"] == 4

    def test_unreachable_warehouse_503(
        self, monkeypatch, internal_client, platform_env
    ):
        engine = FakeEngine(fail_connect=True)
        monkeypatch.setattr(warehouse_routes, "api_engine", lambda: engine)
        response = internal_client.get("/api/v1/warehouse/datasets")
        assert response.status_code == 503
        assert_clean_error_body(response.json())

    def test_unreachable_warehouse_logs_warning(
        self, monkeypatch, internal_client, platform_env, caplog
    ):
        """A degraded dependency must never be invisible to operators
        (OBS-004): every 503 leaves a server-side warning trail."""
        engine = FakeEngine(fail_connect=True)
        monkeypatch.setattr(warehouse_routes, "api_engine", lambda: engine)
        with caplog.at_level(logging.WARNING, logger="app.api.routes.warehouse"):
            response = internal_client.get("/api/v1/warehouse/datasets")
        assert response.status_code == 503
        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING
            and "warehouse unavailable" in r.getMessage()
        ]
        assert len(warnings) == 1


class TestReadDataset:
    def test_read_only_transaction_and_statement_timeout(
        self, internal_client, fake_warehouse
    ):
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders"
        )
        assert response.status_code == 200
        statements = fake_warehouse.connection.statements()
        timeout_idx = statements.index("SET statement_timeout = 15000")
        readonly_idx = statements.index("SET TRANSACTION READ ONLY")
        count_idx = next(i for i, s in enumerate(statements) if "count(*)" in s)
        select_idx = next(
            i for i, s in enumerate(statements) if s.startswith("SELECT * FROM")
        )
        # Guards are issued before any data statement runs, and READ ONLY
        # comes first — SET TRANSACTION must open the autobegun transaction.
        assert readonly_idx < timeout_idx
        assert timeout_idx < count_idx and timeout_idx < select_idx
        assert readonly_idx < count_idx and readonly_idx < select_idx

        body = response.json()
        assert body["data"] == [{"wo_id": 1, "status": "open"}]
        assert body["count"] == 1
        assert body["meta"]["engine"] == "postgres"
        assert body["meta"]["dataset"] == "marts.fct_work_orders"

    def test_unknown_dataset_404(self, internal_client, fake_warehouse):
        response = internal_client.get("/api/v1/warehouse/datasets/marts.secret_table")
        assert response.status_code == 404
        assert_clean_error_body(response.json())

    def test_schema_outside_allowlist_404(self, internal_client, fake_warehouse):
        # control/raw_oracle relations are never discoverable (API-003).
        response = internal_client.get(
            "/api/v1/warehouse/datasets/control.replication_watermarks"
        )
        assert response.status_code == 404

    def test_unknown_filter_column_422(self, internal_client, fake_warehouse):
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders?bad_col=1"
        )
        assert response.status_code == 422
        assert "bad_col" in response.json()["detail"]
        assert_clean_error_body(response.json())

    def test_unknown_order_by_422(self, internal_client, fake_warehouse):
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders?order_by=nope"
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "Unknown order_by column"

    def test_order_dir_pattern_enforced(self, internal_client, fake_warehouse):
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders"
            "?order_by=status&order_dir=asc;drop"
        )
        assert response.status_code == 422

    def test_pagination_hard_cap(self, internal_client, fake_warehouse):
        assert (
            internal_client.get(
                "/api/v1/warehouse/datasets/marts.fct_work_orders?limit=1001"
            ).status_code
            == 422
        )
        assert (
            internal_client.get(
                "/api/v1/warehouse/datasets/marts.fct_work_orders?limit=0"
            ).status_code
            == 422
        )
        ok = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders?limit=1000&offset=10"
        )
        assert ok.status_code == 200
        assert ok.json()["meta"]["limit"] == 1000

    def test_filter_values_travel_as_binds(self, internal_client, fake_warehouse):
        payload = "open' OR '1'='1"
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders",
            params={"status": payload},
        )
        assert response.status_code == 200
        data_calls = [
            (sql, params)
            for sql, params in fake_warehouse.connection.calls
            if sql.startswith("SELECT")
        ]
        assert data_calls, "expected data statements"
        for sql, params in data_calls:
            assert payload not in sql  # never interpolated
            assert '"status"::text = :f_0' in sql
            assert params["f_0"] == payload  # always bound
        assert response.json()["meta"]["filters"] == {"status": payload}

    def test_order_by_quoted_identifier(self, internal_client, fake_warehouse):
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders"
            "?order_by=status&order_dir=desc"
        )
        assert response.status_code == 200
        select_sql = next(
            sql
            for sql, _ in fake_warehouse.connection.calls
            if sql.startswith("SELECT * FROM")
        )
        assert 'ORDER BY "status" DESC' in select_sql
        assert "LIMIT :limit OFFSET :offset" in select_sql

    def test_meta_contains_elapsed_ms_int(self, internal_client, fake_warehouse):
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders"
        )
        assert response.status_code == 200
        elapsed_ms = response.json()["meta"]["elapsed_ms"]
        assert isinstance(elapsed_ms, int)
        assert elapsed_ms >= 0

    def test_log_line_has_dataset_and_elapsed_but_never_filter_values(
        self, internal_client, fake_warehouse, caplog
    ):
        """One telemetry line per read; values never logged (OBS-006/OBS-008)."""
        secret = "super-secret-filter-value"
        with caplog.at_level(logging.INFO, logger="app.api.routes.warehouse"):
            response = internal_client.get(
                "/api/v1/warehouse/datasets/marts.fct_work_orders",
                params={"status": secret},
            )
        assert response.status_code == 200
        lines = [
            record.getMessage()
            for record in caplog.records
            if "warehouse dataset read" in record.getMessage()
        ]
        assert len(lines) == 1  # exactly one telemetry line per request
        line = lines[0]
        assert "dataset=marts.fct_work_orders" in line
        assert "elapsed_ms=" in line
        assert "engine=postgres" in line
        assert "request_id=" in line
        assert "status" in line  # filter COLUMN NAME is allowed
        assert secret not in line  # filter VALUE is not (OBS-006)

    def test_query_failure_maps_to_clean_503(
        self, monkeypatch, internal_client, platform_env
    ):
        def responder(sql, _params):
            if "information_schema.columns" in sql:
                return FakeResult(rows=DATASET_COLUMNS)
            raise RuntimeError(
                'SELECT * FROM "marts"."fct_work_orders" failed at C:\\warehouse\\data'
            )

        engine = FakeEngine(responder)
        monkeypatch.setattr(warehouse_routes, "api_engine", lambda: engine)
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders"
        )
        assert response.status_code == 503
        body = response.json()
        assert "fct_work_orders" not in str(body)
        assert_clean_error_body(body)


class TestFilterOperators:
    """The query-builder operator grammar (IQ-004): allowlisted operators,
    typed bound values, and 422 on anything outside the allowlist."""

    def _select_sql_and_params(self, engine):
        return next(
            (sql, params)
            for sql, params in engine.connection.calls
            if sql.startswith("SELECT * FROM")
        )

    def test_temporal_range_binds_parsed_datetime(
        self, internal_client, fake_warehouse
    ):
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders"
            "?due_at__lte=2026-08-01T00:00:00"
        )
        assert response.status_code == 200
        sql, params = self._select_sql_and_params(fake_warehouse)
        assert '"due_at" <= :f_0' in sql
        import datetime as dt

        assert params["f_0"] == dt.datetime(2026, 8, 1)

    def test_numeric_range_binds_decimal(self, internal_client, fake_warehouse):
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders?qty_ordered__gte=10.5"
        )
        assert response.status_code == 200
        sql, params = self._select_sql_and_params(fake_warehouse)
        assert '"qty_ordered" >= :f_0' in sql
        assert str(params["f_0"]) == "10.5"

    def test_integer_range_binds_int(self, internal_client, fake_warehouse):
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders?wo_id__gt=7"
        )
        assert response.status_code == 200
        sql, params = self._select_sql_and_params(fake_warehouse)
        assert '"wo_id" > :f_0' in sql
        assert params["f_0"] == 7

    def test_invalid_typed_value_is_422_not_503(self, internal_client, fake_warehouse):
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders?due_at__gte=not-a-date"
        )
        assert response.status_code == 422
        assert "due_at__gte" in response.json()["detail"]
        assert_clean_error_body(response.json())

    def test_contains_escapes_like_wildcards(self, internal_client, fake_warehouse):
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders",
            params={"status__contains": "100%_done"},
        )
        assert response.status_code == 200
        sql, params = self._select_sql_and_params(fake_warehouse)
        assert '"status"::text ILIKE :f_0' in sql
        assert params["f_0"] == "%100\\%\\_done%"

    def test_neq_operator(self, internal_client, fake_warehouse):
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders?status__neq=closed"
        )
        assert response.status_code == 200
        sql, params = self._select_sql_and_params(fake_warehouse)
        assert '"status"::text <> :f_0' in sql
        assert params["f_0"] == "closed"

    def test_unknown_operator_422(self, internal_client, fake_warehouse):
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders?status__regex=.*"
        )
        assert response.status_code == 422
        assert "regex" in response.json()["detail"]
        assert_clean_error_body(response.json())

    def test_operator_on_unknown_column_422(self, internal_client, fake_warehouse):
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders?nope__gte=1"
        )
        assert response.status_code == 422

    def test_operators_combine_with_equality(self, internal_client, fake_warehouse):
        response = internal_client.get(
            "/api/v1/warehouse/datasets/marts.fct_work_orders"
            "?status=open&wo_id__gte=5&due_at__lte=2026-12-31"
        )
        assert response.status_code == 200
        sql, params = self._select_sql_and_params(fake_warehouse)
        assert '"status"::text = :f_0' in sql
        assert '"wo_id" >= :f_1' in sql
        assert '"due_at" <= :f_2' in sql
        assert len(params) == 5  # 3 filters + limit + offset
        # meta echoes the raw filter grammar for reproducibility (API-012)
        assert response.json()["meta"]["filters"] == {
            "status": "open",
            "wo_id__gte": "5",
            "due_at__lte": "2026-12-31",
        }


class TestKpis:
    def test_single_kpi_failure_nulls_only_that_key_and_warns(
        self, monkeypatch, internal_client, platform_env, caplog
    ):
        """A missing mart degrades one KPI to null, keeps the rest, rolls
        the transaction back, and leaves a warning trail (no silent nulls)."""

        def responder(sql, _params):
            if "marts.fct_quality_inspections" in sql:
                raise RuntimeError("relation marts.fct_quality_inspections missing")
            if "count(*)" in sql or "SELECT round" in sql:
                return FakeResult(scalar=7)
            return None

        engine = FakeEngine(responder)
        monkeypatch.setattr(warehouse_routes, "api_engine", lambda: engine)
        with caplog.at_level(logging.WARNING, logger="app.api.routes.warehouse"):
            response = internal_client.get("/api/v1/warehouse/kpis")
        assert response.status_code == 200
        kpis = response.json()["kpis"]
        assert kpis["quality_pass_rate_30d"] is None  # only the broken KPI
        assert kpis["production_runs_30d"] == 7
        assert kpis["open_work_orders"] == 7
        assert kpis["machines_tracked"] == 7
        # The failed statement was rolled back so later KPIs still run —
        # and the transaction guards were re-armed for the fresh transaction
        # the rollback implicitly opens.
        statements = engine.connection.statements()
        rollback_idx = statements.index("<rollback>")
        assert statements.count("SET TRANSACTION READ ONLY") == 2
        assert statements.count("SET statement_timeout = 15000") == 2
        assert any(
            s == "SET TRANSACTION READ ONLY" for s in statements[rollback_idx + 1 :]
        )
        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "warehouse kpi" in r.getMessage()
        ]
        assert len(warnings) == 1
        assert "quality_pass_rate_30d" in warnings[0].getMessage()
        # The 200 body never carries the underlying error.
        assert_clean_error_body(response.json())

    def test_kpis_meta_contains_elapsed_ms_int(self, internal_client, fake_warehouse):
        response = internal_client.get("/api/v1/warehouse/kpis")
        assert response.status_code == 200
        statements = fake_warehouse.connection.statements()
        assert "SET TRANSACTION READ ONLY" in statements
        assert "SET statement_timeout = 15000" in statements
        body = response.json()
        assert set(body["kpis"]) == {
            "production_runs_30d",
            "open_work_orders",
            "machines_tracked",
            "quality_pass_rate_30d",
            "open_backlog_value",
            "mrp_items_short",
        }
        assert isinstance(body["meta"]["elapsed_ms"], int)
        assert body["meta"]["engine"] == "postgres"
