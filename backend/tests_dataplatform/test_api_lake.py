"""/lake endpoints against a real tmp DuckDB catalog over published Parquet.

Contract parity with /warehouse is part of the suite: canonical `omega.*`
ids (physical `raw_oracle.*` accepted as the deprecated alias, API-016),
version metadata, the shared `column[__op]=value` filter grammar with typed
binds, and `order_by`/`order_dir`.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager

import pytest

from app.dataplatform.lake.duckdb_catalog import LakeQueryTimeoutError, refresh_catalog
from app.dataplatform.registry import Registry
from tests_dataplatform.conftest import assert_clean_error_body
from tests_dataplatform.test_duckdb_catalog import publish_machines


@pytest.fixture
def lake_catalog(platform_env, registry, machines_inferred):
    """Publish real Parquet for machines + refresh the tmp DuckDB catalog."""
    small = Registry(contracts={"OMEGA.MACHINES": registry.get("OMEGA.MACHINES")})
    publish_machines(platform_env, machines_inferred, scn=4242, rows=5)
    refresh_catalog(small, platform_env)
    return platform_env


class TestAuth:
    def test_unauthenticated_requests_rejected(self, anon_client, platform_env):
        for url in (
            "/api/v1/lake/datasets",
            "/api/v1/lake/datasets/omega.machines",
            "/api/v1/lake/loads",
        ):
            response = anon_client.get(url)
            assert response.status_code == 401, url

    def test_customer_portal_user_rejected(self, api_app, platform_env):
        from tests_dataplatform.conftest import _client

        client = _client(api_app, "customer")
        try:
            response = client.get("/api/v1/lake/datasets")
            assert response.status_code == 403
        finally:
            api_app.dependency_overrides.clear()


class TestListDatasets:
    def test_missing_catalog_returns_503(self, internal_client, platform_env):
        response = internal_client.get("/api/v1/lake/datasets")
        assert response.status_code == 503
        assert "not available" in response.json()["detail"]
        assert_clean_error_body(response.json())

    def test_lists_canonical_ids_with_version(self, internal_client, lake_catalog):
        response = internal_client.get("/api/v1/lake/datasets")
        assert response.status_code == 200
        body = response.json()
        datasets = {d["dataset"]: d for d in body["data"]}
        # Canonical id is omega.*; the physical spelling is not advertised.
        assert "omega.machines" in datasets
        assert "raw_oracle.machines" not in datasets
        entry = datasets["omega.machines"]
        assert entry["engine"] == "duckdb"
        assert entry["type"] == "VIEW"
        assert entry["version"] == "v1"
        assert entry["schema"] == "raw_oracle"  # physical location is metadata
        assert body["count"] == len(body["data"])


class TestReadDataset:
    def test_reads_rows_with_provenance_meta(self, internal_client, lake_catalog):
        response = internal_client.get("/api/v1/lake/datasets/omega.machines")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 5
        assert len(body["data"]) == 5
        row = body["data"][0]
        assert {"machine_id", "name", "_load_id", "_source_scn"} <= set(row)
        meta = body["meta"]
        assert meta["dataset"] == "omega.machines"
        assert meta["version"] == "v1"
        assert meta["engine"] == "duckdb"
        assert meta["limit"] == 100 and meta["offset"] == 0
        assert meta["filters"] == {}
        assert "generated_at" in meta

    def test_deprecated_physical_alias_resolves_to_canonical(
        self, internal_client, lake_catalog
    ):
        """API-016: raw_oracle.* keeps working, but meta speaks canonical."""
        response = internal_client.get("/api/v1/lake/datasets/raw_oracle.machines")
        assert response.status_code == 200
        assert response.json()["meta"]["dataset"] == "omega.machines"

    def test_pagination(self, internal_client, lake_catalog):
        response = internal_client.get(
            "/api/v1/lake/datasets/omega.machines?limit=2&offset=4"
        )
        body = response.json()
        assert body["count"] == 5  # total, not page size
        assert len(body["data"]) == 1  # only one row past offset 4
        assert body["meta"]["limit"] == 2 and body["meta"]["offset"] == 4

    def test_limit_above_hard_cap_rejected(self, internal_client, lake_catalog):
        response = internal_client.get(
            "/api/v1/lake/datasets/omega.machines?limit=1001"
        )
        assert response.status_code == 422
        response = internal_client.get(
            "/api/v1/lake/datasets/omega.machines?limit=0"
        )
        assert response.status_code == 422

    def test_unknown_dataset_404(self, internal_client, lake_catalog):
        response = internal_client.get("/api/v1/lake/datasets/omega.nope")
        assert response.status_code == 404
        # Same wording as /warehouse (error-body parity).
        assert response.json()["detail"] == "Unknown dataset"
        assert_clean_error_body(response.json())

    def test_unknown_filter_column_422(self, internal_client, lake_catalog):
        response = internal_client.get(
            "/api/v1/lake/datasets/omega.machines?not_a_column=1"
        )
        assert response.status_code == 422
        assert "not_a_column" in response.json()["detail"]
        assert_clean_error_body(response.json())

    def test_filter_values_are_bound_not_concatenated(
        self, internal_client, lake_catalog
    ):
        # A classic injection payload must behave as an inert literal.
        response = internal_client.get(
            "/api/v1/lake/datasets/omega.machines",
            params={"name": "x' OR '1'='1"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 0
        assert body["data"] == []

    def test_equality_filter_matches(self, internal_client, lake_catalog):
        response = internal_client.get(
            "/api/v1/lake/datasets/omega.machines", params={"name": "name-2"}
        )
        body = response.json()
        assert body["count"] == 1
        assert body["data"][0]["name"] == "name-2"
        assert body["data"][0]["machine_id"] == 2
        assert body["meta"]["filters"] == {"name": "name-2"}

    def test_operator_grammar_matches_warehouse(self, internal_client, lake_catalog):
        """The same column__op grammar the warehouse explorer emits (IQ-004)."""
        gte = internal_client.get(
            "/api/v1/lake/datasets/omega.machines?machine_id__gte=3"
        )
        assert gte.status_code == 200
        assert gte.json()["count"] == 2
        neq = internal_client.get(
            "/api/v1/lake/datasets/omega.machines?name__neq=name-2"
        )
        assert neq.json()["count"] == 4
        contains = internal_client.get(
            "/api/v1/lake/datasets/omega.machines?name__contains=ame-1"
        )
        assert contains.json()["count"] == 1
        assert contains.json()["data"][0]["name"] == "name-1"

    def test_contains_wildcards_match_literally(self, internal_client, lake_catalog):
        """LIKE metacharacters in the value are escaped (API-003)."""
        response = internal_client.get(
            "/api/v1/lake/datasets/omega.machines?name__contains=%25"
        )
        assert response.status_code == 200
        assert response.json()["count"] == 0  # no literal '%' in any name

    def test_unknown_operator_422(self, internal_client, lake_catalog):
        response = internal_client.get(
            "/api/v1/lake/datasets/omega.machines?name__like=foo"
        )
        assert response.status_code == 422
        assert "operator" in response.json()["detail"]
        assert_clean_error_body(response.json())

    def test_typed_comparison_value_mismatch_422(self, internal_client, lake_catalog):
        response = internal_client.get(
            "/api/v1/lake/datasets/omega.machines?machine_id__gt=abc"
        )
        assert response.status_code == 422
        assert "Invalid value" in response.json()["detail"]
        assert_clean_error_body(response.json())

    def test_order_by(self, internal_client, lake_catalog):
        response = internal_client.get(
            "/api/v1/lake/datasets/omega.machines"
            "?order_by=machine_id&order_dir=desc&limit=1"
        )
        assert response.status_code == 200
        assert response.json()["data"][0]["machine_id"] == 4
        unknown = internal_client.get(
            "/api/v1/lake/datasets/omega.machines?order_by=nope"
        )
        assert unknown.status_code == 422

    def test_missing_catalog_returns_503_on_read(self, internal_client, platform_env):
        response = internal_client.get("/api/v1/lake/datasets/omega.machines")
        assert response.status_code == 503
        assert_clean_error_body(response.json())

    def test_query_timeout_maps_to_504_with_safe_body(
        self, monkeypatch, internal_client, lake_catalog
    ):
        """A bounded-execution interrupt surfaces as 504, no internals (DDB-006)."""
        import app.api.routes.lake as lake_routes

        @contextmanager
        def _timeout_scope(*_args, **_kwargs):
            def _run(*_a, **_k):
                raise LakeQueryTimeoutError()

            yield _run

        monkeypatch.setattr(
            lake_routes.duckdb_catalog, "read_scope", _timeout_scope
        )
        response = internal_client.get("/api/v1/lake/datasets/omega.machines")
        assert response.status_code == 504
        body = response.json()
        assert body["detail"] == "Lake query exceeded the time limit"
        assert_clean_error_body(body)


class TestReadTelemetry:
    """Per-query telemetry on the governed lake read path (OBS-008/IQ-013)."""

    def test_meta_contains_elapsed_ms_int(self, internal_client, lake_catalog):
        response = internal_client.get("/api/v1/lake/datasets/omega.machines")
        assert response.status_code == 200
        elapsed_ms = response.json()["meta"]["elapsed_ms"]
        assert isinstance(elapsed_ms, int)
        assert elapsed_ms >= 0

    def test_log_line_has_dataset_and_elapsed_but_never_filter_values(
        self, internal_client, lake_catalog, caplog
    ):
        secret = "name-2"
        with caplog.at_level(logging.INFO, logger="app.api.routes.lake"):
            response = internal_client.get(
                "/api/v1/lake/datasets/omega.machines", params={"name": secret}
            )
        assert response.status_code == 200
        lines = [
            record.getMessage()
            for record in caplog.records
            if "lake dataset read" in record.getMessage()
        ]
        assert len(lines) == 1  # exactly one telemetry line per request
        line = lines[0]
        assert "dataset=omega.machines" in line
        assert "elapsed_ms=" in line
        assert "engine=duckdb" in line
        assert "request_id=" in line
        assert "name" in line  # filter COLUMN NAME is allowed
        assert secret not in line  # filter VALUE is not (OBS-006)


class TestListLoads:
    def test_lists_published_manifests(self, internal_client, lake_catalog):
        response = internal_client.get("/api/v1/lake/loads")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        entry = body["data"][0]
        assert entry["table"] == "OMEGA.MACHINES"
        assert entry["destination"] == "machines"
        assert entry["scn"] == 4242
        assert entry["row_count"] == 5
        assert entry["status"] == "published"

    def test_filter_by_table_name(self, internal_client, lake_catalog):
        response = internal_client.get("/api/v1/lake/loads?table=machines")
        assert response.json()["count"] == 1
        response = internal_client.get("/api/v1/lake/loads?table=OMEGA.MACHINES")
        assert response.json()["count"] == 1

    def test_unknown_table_404(self, internal_client, lake_catalog):
        response = internal_client.get("/api/v1/lake/loads?table=not_a_table")
        assert response.status_code == 404
        assert_clean_error_body(response.json())
