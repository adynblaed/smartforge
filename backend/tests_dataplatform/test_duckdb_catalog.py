"""DuckDB catalog over real published Parquet in tmp dirs."""

from __future__ import annotations

import duckdb
import pytest

from app.dataplatform.lake.duckdb_catalog import (
    LakeQueryTimeoutError,
    list_relations,
    query_readonly,
    reader_connection,
    refresh_catalog,
    writer_connection,
)
from app.dataplatform.lake.parquet import publish_load, write_staged_load
from app.dataplatform.oracle.extractor import build_arrow_schema
from app.dataplatform.registry import Registry
from tests_dataplatform.conftest import fill_batch, make_boundary
from tests_dataplatform.test_lake_parquet import make_manifest, stage


@pytest.fixture
def lake_settings(make_settings):
    return make_settings(DUCKDB_MEMORY_LIMIT="1GB", DUCKDB_THREADS=2)


@pytest.fixture
def small_registry(registry) -> Registry:
    """Two real contracts only, so refresh_catalog stays fast."""
    return Registry(
        contracts={
            "OMEGA.MACHINES": registry.get("OMEGA.MACHINES"),
            "OMEGA.SUPPLIERS": registry.get("OMEGA.SUPPLIERS"),
        }
    )


def publish_machines(settings, machines_inferred, scn=4242, rows=7):
    boundary = make_boundary(scn)
    staging_dir, result = stage(
        settings, machines_inferred, boundary, num_batches=1, rows_per_batch=rows
    )
    manifest = make_manifest(
        machines_inferred, boundary, result.row_count, result.files
    )
    return publish_load(
        staging_dir,
        machines_inferred,
        boundary,
        manifest,
        kind="snapshot",
        settings=settings,
    )


class TestRefreshCatalog:
    def test_creates_views_only_for_published_tables(
        self, lake_settings, small_registry, machines_inferred
    ):
        publish_machines(lake_settings, machines_inferred)
        # Also park data in staging + quarantine to prove it is never exposed.
        schema = build_arrow_schema(machines_inferred)
        write_staged_load(
            [fill_batch(schema, 3)],
            schema,
            load_id="20990101T000000Z_9",
            table_name="machines",
            settings=lake_settings,
        )
        registered = refresh_catalog(small_registry, lake_settings)
        assert registered == ["machines"]  # suppliers has no published data

        relations = list_relations(lake_settings)
        names = {(r["schema"], r["name"]) for r in relations}
        assert ("raw_oracle", "machines") in names
        assert ("raw_oracle", "suppliers") not in names

    def test_view_sql_references_published_paths_only(
        self, lake_settings, small_registry, machines_inferred
    ):
        publish_machines(lake_settings, machines_inferred)
        refresh_catalog(small_registry, lake_settings)
        with reader_connection(lake_settings) as connection:
            rows = connection.execute(
                "SELECT view_name, sql FROM duckdb_views() WHERE schema_name = 'raw_oracle'"
            ).fetchall()
        assert rows, "expected at least one raw_oracle view"
        for _name, sql in rows:
            assert "published" in sql
            assert "_staging" not in sql
            assert "quarantine" not in sql

    def test_view_reads_published_rows(
        self, lake_settings, small_registry, machines_inferred
    ):
        publish_machines(lake_settings, machines_inferred, rows=7)
        refresh_catalog(small_registry, lake_settings)
        names, rows = query_readonly(
            'SELECT count(*) FROM raw_oracle."machines"', settings=lake_settings
        )
        assert rows[0][0] == 7

    def test_refresh_is_idempotent(
        self, lake_settings, small_registry, machines_inferred
    ):
        publish_machines(lake_settings, machines_inferred)
        assert refresh_catalog(small_registry, lake_settings) == ["machines"]
        assert refresh_catalog(small_registry, lake_settings) == ["machines"]


class TestReaderConnection:
    def test_reader_is_read_only(
        self, lake_settings, small_registry, machines_inferred
    ):
        publish_machines(lake_settings, machines_inferred)
        refresh_catalog(small_registry, lake_settings)
        with reader_connection(lake_settings) as connection:
            with pytest.raises(duckdb.Error):
                connection.execute("CREATE TABLE smuggled (i INTEGER)")
            with pytest.raises(duckdb.Error):
                connection.execute("CREATE SCHEMA smuggled_schema")
            with pytest.raises(duckdb.Error):
                connection.execute("INSERT INTO raw_oracle.machines VALUES (1)")

    def test_resource_limits_applied(
        self, lake_settings, small_registry, machines_inferred
    ):
        publish_machines(lake_settings, machines_inferred)
        refresh_catalog(small_registry, lake_settings)
        with reader_connection(lake_settings) as connection:
            threads = connection.execute(
                "SELECT current_setting('threads')"
            ).fetchone()[0]
            memory_limit = connection.execute(
                "SELECT current_setting('memory_limit')"
            ).fetchone()[0]
        assert int(threads) == 2
        # 1GB normalizes to ~953.6 MiB inside DuckDB.
        assert memory_limit.endswith(("MiB", "GiB"))
        assert memory_limit != "80% of RAM"

    def test_writer_limits_applied_too(self, lake_settings):
        with writer_connection(lake_settings) as connection:
            threads = connection.execute(
                "SELECT current_setting('threads')"
            ).fetchone()[0]
        assert int(threads) == 2


class TestQueryReadonly:
    def test_binds_parameters(self, lake_settings, small_registry, machines_inferred):
        publish_machines(lake_settings, machines_inferred, rows=5)
        refresh_catalog(small_registry, lake_settings)
        names, rows = query_readonly(
            'SELECT machine_id, name FROM raw_oracle."machines" '
            "WHERE name = ? ORDER BY machine_id",
            ["name-2"],
            settings=lake_settings,
        )
        assert names == ["machine_id", "name"]
        assert rows == [(2, "name-2")]

    def test_bound_injection_value_matches_nothing(
        self, lake_settings, small_registry, machines_inferred
    ):
        publish_machines(lake_settings, machines_inferred, rows=5)
        refresh_catalog(small_registry, lake_settings)
        _, rows = query_readonly(
            'SELECT count(*) FROM raw_oracle."machines" WHERE CAST(name AS VARCHAR) = ?',
            ["x' OR '1'='1"],
            settings=lake_settings,
        )
        assert rows[0][0] == 0

    def test_missing_catalog_raises(self, make_settings):
        settings = make_settings()
        with pytest.raises(duckdb.Error):
            query_readonly("SELECT 1", settings=settings)


class TestQueryTimeout:
    """Bounded execution for read-only lake queries (DDB-006)."""

    EXPENSIVE_SQL = (
        "SELECT sum(a.range * b.range) FROM range(100000000) a CROSS JOIN range(1000) b"
    )

    def test_expensive_query_interrupted_with_safe_error(
        self, lake_settings, small_registry, machines_inferred
    ):
        publish_machines(lake_settings, machines_inferred)
        refresh_catalog(small_registry, lake_settings)
        with pytest.raises(LakeQueryTimeoutError) as excinfo:
            query_readonly(self.EXPENSIVE_SQL, settings=lake_settings, timeout_ms=50)
        message = str(excinfo.value)
        assert message == "Lake query exceeded the time limit"
        assert "range" not in message  # no query text leaks (OBS-006)

    def test_connection_cleaned_up_after_timeout(
        self, lake_settings, small_registry, machines_inferred
    ):
        publish_machines(lake_settings, machines_inferred, rows=7)
        refresh_catalog(small_registry, lake_settings)
        with pytest.raises(LakeQueryTimeoutError):
            query_readonly(self.EXPENSIVE_SQL, settings=lake_settings, timeout_ms=50)
        # The catalog stays fully usable: a fresh read-only query succeeds.
        _, rows = query_readonly(
            'SELECT count(*) FROM raw_oracle."machines"', settings=lake_settings
        )
        assert rows[0][0] == 7

    def test_normal_query_unaffected_by_default_timeout(
        self, lake_settings, small_registry, machines_inferred
    ):
        publish_machines(lake_settings, machines_inferred, rows=5)
        refresh_catalog(small_registry, lake_settings)
        assert lake_settings.API_STATEMENT_TIMEOUT_MS == 15_000
        names, rows = query_readonly(
            'SELECT count(*) FROM raw_oracle."machines"', settings=lake_settings
        )
        assert names == ["count_star()"]
        assert rows == [(5,)]
