"""Offline test harness for the SmartForge data platform.

No Oracle, no PostgreSQL server, no Docker:
  * oracledb connection entry points are blocked for every test (autouse) so
    a stray code path can never dial a real database;
  * Postgres engines are replaced by recording fakes (see FakeEngine);
  * pyarrow / DuckDB / the filesystem are real, rooted in pytest tmp dirs via
    PlatformSettings constructed from monkeypatched env vars.
"""

from __future__ import annotations

import datetime as dt
import decimal
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

# app.core.config.Settings has required fields normally supplied by the repo
# .env; provide harmless offline defaults BEFORE any `app` import so the
# suite runs with no .env, no services, and no real credentials.
os.environ.setdefault("PROJECT_NAME", "SmartForge Test Suite")
os.environ.setdefault("POSTGRES_SERVER", "postgres.invalid")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "offline-test-only")
os.environ.setdefault("POSTGRES_DB", "app")
os.environ.setdefault("FIRST_SUPERUSER", "admin@example.com")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "offline-test-only")
# App-layer rate limiting must never throttle test suites (API-017).
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import oracledb
import pyarrow as pa
import pytest
from fastapi import HTTPException, Request

from app.dataplatform.config import PlatformSettings, get_platform_settings
from app.dataplatform.oracle.metadata import InferredColumn, InferredTable
from app.dataplatform.oracle.snapshot import SourceBoundary
from app.dataplatform.registry import TableContract, load_registry, load_type_mappings

# ---------------------------------------------------------------------------
# Safety net: no test may ever open a real Oracle connection.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_real_oracle(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    def _blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(
            "Test attempted a real Oracle connection — oracledb is mocked at "
            "the module boundary for this suite."
        )

    monkeypatch.setattr(oracledb, "connect", _blocked)
    monkeypatch.setattr(oracledb, "create_pool", _blocked)
    import app.dataplatform.oracle.connection as oracle_connection_module

    monkeypatch.setattr(oracle_connection_module, "_pool", None)
    yield


# ---------------------------------------------------------------------------
# Platform settings rooted in tmp dirs
# ---------------------------------------------------------------------------


def _clear_settings_caches() -> None:
    from app.dataplatform.warehouse import postgres as warehouse_postgres

    get_platform_settings.cache_clear()
    warehouse_postgres.loader_engine.cache_clear()
    warehouse_postgres.api_engine.cache_clear()


@pytest.fixture
def platform_env(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> Generator[PlatformSettings, None, None]:
    """Point the process-global get_platform_settings() at tmp dirs."""
    monkeypatch.setenv("LAKE_ROOT", str(tmp_path / "lake"))
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "catalog" / "lake.duckdb"))
    monkeypatch.setenv("OMEGA_ORACLE_HOST", "oracle.invalid")
    monkeypatch.setenv("OMEGA_ORACLE_PASSWORD", "not-a-real-password")
    monkeypatch.setenv("POSTGRES_SERVER", "postgres.invalid")
    monkeypatch.setenv("WAREHOUSE_LOADER_PASSWORD", "test")
    monkeypatch.setenv("WAREHOUSE_API_PASSWORD", "test")
    _clear_settings_caches()
    yield get_platform_settings()
    _clear_settings_caches()


@pytest.fixture
def make_settings(tmp_path):
    """Factory for explicitly constructed settings (never real paths/DSNs)."""

    def _make(**overrides: Any) -> PlatformSettings:
        defaults: dict[str, Any] = {
            "_env_file": None,
            "LAKE_ROOT": tmp_path / "lake",
            "DUCKDB_PATH": tmp_path / "catalog" / "lake.duckdb",
            "OMEGA_ORACLE_HOST": "oracle.invalid",
            "POSTGRES_SERVER": "postgres.invalid",
        }
        defaults.update(overrides)
        return PlatformSettings(**defaults)

    return _make


# ---------------------------------------------------------------------------
# Real contracts / mappings from config/*.yml
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def registry():
    return load_registry()


@pytest.fixture(scope="session")
def type_mappings():
    return load_type_mappings()


@pytest.fixture
def machines_contract(registry) -> TableContract:
    return registry.get("OMEGA.MACHINES")


@pytest.fixture
def telemetry_contract(registry) -> TableContract:
    return registry.get("OMEGA.TELEMETRY_EVENTS")


MACHINE_COLUMNS = [
    ("MACHINE_ID", "NUMBER", 18, 0, False, "BIGINT", "int64", "BIGINT"),
    ("NAME", "VARCHAR2", None, None, True, "TEXT", "string", "VARCHAR"),
    (
        "LAST_UPDATE_TS",
        "DATE",
        None,
        None,
        True,
        "TIMESTAMP WITHOUT TIME ZONE",
        "timestamp(us)",
        "TIMESTAMP",
    ),
]


def build_inferred(
    contract: TableContract,
    columns: list[tuple] | None = None,
) -> InferredTable:
    columns = columns or MACHINE_COLUMNS
    inferred_columns = [
        InferredColumn(
            name=name,
            destination_name=name.lower(),
            oracle_type=oracle_type,
            data_precision=precision,
            data_scale=scale,
            nullable=nullable,
            postgres_type=pg,
            arrow_type=arrow,
            duckdb_type=ddb,
            is_primary_key=name in contract.primary_key,
        )
        for name, oracle_type, precision, scale, nullable, pg, arrow, ddb in columns
    ]
    table = InferredTable(contract=contract, columns=inferred_columns)
    table.schema_hash = table.compute_schema_hash()
    return table


@pytest.fixture
def machines_inferred(machines_contract) -> InferredTable:
    return build_inferred(machines_contract)


@pytest.fixture
def boundary() -> SourceBoundary:
    captured = dt.datetime(2026, 7, 15, 10, 0, 0, tzinfo=dt.timezone.utc)
    return SourceBoundary(
        scn=5000,
        source_timestamp_utc=captured,
        captured_at_utc=captured,
    )


def make_boundary(scn: int) -> SourceBoundary:
    captured = dt.datetime(
        2026, 7, 15, 10, 0, 0, tzinfo=dt.timezone.utc
    ) + dt.timedelta(seconds=scn)
    return SourceBoundary(
        scn=scn, source_timestamp_utc=captured, captured_at_utc=captured
    )


def fill_batch(schema: pa.Schema, num_rows: int, start: int = 0) -> pa.RecordBatch:
    """Build a typed RecordBatch with deterministic values for any schema."""
    arrays: list[pa.Array] = []
    now = dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc)
    for field in schema:
        t = field.type
        if pa.types.is_integer(t):
            values: list[Any] = [start + i for i in range(num_rows)]
        elif pa.types.is_boolean(t):
            values = [False] * num_rows
        elif pa.types.is_decimal(t):
            values = [decimal.Decimal(start + i) for i in range(num_rows)]
        elif pa.types.is_timestamp(t):
            base = now if t.tz else now.replace(tzinfo=None)
            values = [base + dt.timedelta(minutes=start + i) for i in range(num_rows)]
        elif pa.types.is_floating(t):
            values = [float(start + i) for i in range(num_rows)]
        elif pa.types.is_binary(t) or pa.types.is_large_binary(t):
            values = [b"\x00"] * num_rows
        else:
            values = [f"{field.name}-{start + i}" for i in range(num_rows)]
        arrays.append(pa.array(values, type=t))
    return pa.RecordBatch.from_arrays(arrays, schema=schema)


# ---------------------------------------------------------------------------
# Recording fakes for SQLAlchemy engines / connections
# ---------------------------------------------------------------------------


class FakeResult:
    def __init__(
        self,
        *,
        scalar: Any = None,
        rows: list[tuple] | None = None,
        one: tuple | None = None,
        mapping_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self._scalar = scalar
        self._rows = rows or []
        self._one = one
        self._mapping_rows = mapping_rows or []

    def scalar(self) -> Any:
        return self._scalar

    def fetchall(self) -> list[tuple]:
        return self._rows

    def fetchone(self) -> tuple | None:
        return self._one

    def mappings(self) -> FakeResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._mapping_rows


class FakeConnection:
    """Records every executed statement; answers via a scripted responder."""

    def __init__(self, responder=None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._responder = responder

    def execute(self, statement: Any, params: Any = None) -> FakeResult:
        sql = str(statement)
        self.calls.append((sql, params))
        if self._responder is not None:
            result = self._responder(sql, params)
            if result is not None:
                return result
        return FakeResult()

    def rollback(self) -> None:
        self.calls.append(("<rollback>", None))

    def statements(self) -> list[str]:
        return [sql for sql, _ in self.calls]


class FakeEngine:
    def __init__(self, responder=None, *, fail_connect: bool = False) -> None:
        self.connection = FakeConnection(responder)
        self.fail_connect = fail_connect

    @contextmanager
    def connect(self):
        if self.fail_connect:
            raise ConnectionError("fake warehouse is unreachable")
        yield self.connection

    @contextmanager
    def begin(self):
        if self.fail_connect:
            raise ConnectionError("fake warehouse is unreachable")
        yield self.connection


# ---------------------------------------------------------------------------
# Fake Oracle connection/cursor (for extractor + reconcile tests)
# ---------------------------------------------------------------------------


class FakeOracleCursor:
    def __init__(self, script: list[list[tuple]]) -> None:
        self._script = list(script)
        self.executed: list[tuple[str, Any]] = []
        self.arraysize = 0
        self.prefetchrows = 0

    def execute(self, sql: str, binds: Any = None) -> None:
        self.executed.append((sql, binds))

    def fetchall(self) -> list[tuple]:
        return self._script.pop(0) if self._script else []

    def fetchone(self) -> tuple | None:
        rows = self.fetchall()
        return rows[0] if rows else None

    def close(self) -> None:
        pass


class FakeOracleConnection:
    def __init__(self, script: list[list[tuple]] | None = None) -> None:
        self._cursor = FakeOracleCursor(script or [])

    def cursor(self) -> FakeOracleCursor:
        return self._cursor


# ---------------------------------------------------------------------------
# FastAPI app + auth clients (mirrors tests_smartforge/conftest.py)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def api_app():
    from app.core.config import settings as core_settings

    core_settings.SIMULATOR_ENABLED = False
    core_settings.RATE_LIMIT_ENABLED = False
    from app.main import app

    return app


def _install_user_override(app) -> None:
    """Resolve the current user from a test header; no DB needed here —
    the lake/warehouse/platform routes never use get_db."""
    from app import models as m
    from app.api.deps import get_current_user

    def current_user_override(request: Request):
        kind = request.headers.get("x-test-user")
        if kind is None:
            raise HTTPException(status_code=401, detail="No test user")
        if kind == "superuser":
            return m.User(
                email="admin@smartforge.com",
                hashed_password="x",
                is_superuser=True,
                role=m.UserRole.admin,
            )
        if kind == "customer":
            return m.User(
                email="buyer@acme-robotics.com",
                hashed_password="x",
                role=m.UserRole.customer,
            )
        return m.User(
            email="operator@smartforge.com",
            hashed_password="x",
            role=m.UserRole.operator,
        )

    app.dependency_overrides[get_current_user] = current_user_override


def _client(api_app, kind: str):
    from fastapi.testclient import TestClient

    _install_user_override(api_app)
    # Not a context manager -> app lifespan (simulator) does not run.
    return TestClient(api_app, headers={"x-test-user": kind})


@pytest.fixture
def internal_client(api_app):
    yield _client(api_app, "internal")
    api_app.dependency_overrides.clear()


@pytest.fixture
def superuser_client(api_app):
    yield _client(api_app, "superuser")
    api_app.dependency_overrides.clear()


@pytest.fixture
def anon_client(api_app):
    """No dependency override at all: the real OAuth2 dependency runs."""
    from fastapi.testclient import TestClient

    saved = dict(api_app.dependency_overrides)
    api_app.dependency_overrides.clear()
    yield TestClient(api_app)
    api_app.dependency_overrides.clear()
    api_app.dependency_overrides.update(saved)


def assert_clean_error_body(body: Any) -> None:
    """Induced error responses must never leak SQL text or file paths."""
    text = str(body).upper()
    for fragment in (
        "SELECT ",
        "INSERT ",
        "UPDATE ",
        "FROM RAW_ORACLE",
        ":\\",
        "/HOME/",
    ):
        assert fragment not in text, f"error body leaks internals: {body!r}"
