"""Isolated test harness for the SmartForge platform.

These tests run against an in-memory SQLite database with FastAPI dependency
overrides, so they never touch the sandbox Postgres database and need no running
services. Auth is exercised for real: only `get_current_user` and `get_db` are
overridden, so the role-gating dependencies (internal vs customer) run as in
production.
"""

from collections.abc import Generator

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models as m
from app.api.deps import get_current_user, get_db
from app.core import seed as seed_mod
from app.core.config import settings
from app.main import app

# Never start the in-process telemetry simulator during tests.
settings.SIMULATOR_ENABLED = False
# Rate limiting stays off by default so suites are never throttled;
# test_rate_limiting.py re-enables it explicitly via monkeypatch.
settings.RATE_LIMIT_ENABLED = False


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="session")
def session_fixture(engine) -> Generator[Session, None, None]:
    with Session(engine) as session:
        seed_mod.seed_sandbox(session)
        yield session


def _install_overrides(engine) -> None:
    """Install request-scoped overrides.

    Auth is resolved per-request from the `x-test-user-email` header so multiple
    clients (different actors) can coexist in one test without clobbering a
    shared global override. Role-gating deps still run for real.
    """

    def get_db_override() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    def current_user_override(request: Request) -> m.User:
        email = request.headers.get("x-test-user-email")
        with Session(engine) as s:
            user = s.exec(select(m.User).where(m.User.email == email)).first()
        if user is None:
            raise HTTPException(status_code=401, detail="No test user")
        return user

    app.dependency_overrides[get_db] = get_db_override
    app.dependency_overrides[get_current_user] = current_user_override


def _client_for(engine, email: str) -> TestClient:
    _install_overrides(engine)
    # Not used as a context manager → app lifespan (simulator) does not run.
    return TestClient(app, headers={"x-test-user-email": email})


# `session` is requested (not referenced) so the DB is seeded before the client runs.
@pytest.fixture(name="internal_client")
def internal_client_fixture(session, engine) -> Generator[TestClient, None, None]:  # noqa: ARG001
    yield _client_for(engine, "operator@smartforge.com")
    app.dependency_overrides.clear()


@pytest.fixture(name="customer_client")
def customer_client_fixture(session, engine) -> Generator[TestClient, None, None]:  # noqa: ARG001
    yield _client_for(engine, "buyer@acme-robotics.com")
    app.dependency_overrides.clear()


@pytest.fixture(name="other_customer_client")
def other_customer_client_fixture(session, engine) -> Generator[TestClient, None, None]:  # noqa: ARG001
    yield _client_for(engine, "buyer@globex-mfg.com")
    app.dependency_overrides.clear()
