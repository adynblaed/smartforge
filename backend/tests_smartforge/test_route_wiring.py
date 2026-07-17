"""Route wiring and security-posture sweep across the ENTIRE API surface.

Enumerates every registered route (instead of hand-picking endpoints) so a
newly added router can never ship unauthenticated by accident (IAM-005,
API-005): anonymous requests must be rejected everywhere except a reviewed
public allowlist, and every parameterless GET must be healthy for a
superuser against seeded sandbox data.
"""

import uuid
from collections.abc import Generator

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.deps import get_db
from app.main import app

# Paths (full, as registered) that are deliberately reachable without a
# bearer token. Adding a path here is a security decision — review it.
PUBLIC_PATHS = {
    "/api/v1/login/access-token",  # issues tokens
    "/api/v1/password-recovery/{email}",
    "/api/v1/password-recovery-html-content/{email}",
    "/api/v1/reset-password/",
    "/api/v1/users/signup",  # open registration (sandbox policy)
    "/api/v1/utils/health-check/",  # liveness (no internals exposed)
    "/api/v1/metrics",  # Prometheus scrape (loopback-only in compose)
}

# Local-environment-only conveniences (never registered in staging/prod —
# see app/api/main.py) and template email utils gated by their own deps.
LOCAL_ONLY_PREFIXES = ("/api/v1/private",)


def _dummy_path(path: str) -> str:
    """Fill path params with syntactically valid dummies."""
    out = path
    while "{" in out:
        start = out.index("{")
        end = out.index("}", start)
        name = out[start + 1 : end].split(":")[0]
        value = "test%40example.com" if "email" in name else str(uuid.uuid4())
        out = out[:start] + value + out[end + 1 :]
    return out


def _http_routes() -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute)]


@pytest.fixture(name="anon_client")
def anon_client_fixture(session, engine) -> Generator[TestClient, None, None]:  # noqa: ARG001
    """Client with the DB overridden but REAL authentication deps."""

    def get_db_override() -> Generator[Session, None, None]:
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = get_db_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_every_route_lives_under_api_v1() -> None:
    for route in _http_routes():
        assert route.path.startswith("/api/v1"), route.path


def test_no_duplicate_method_path_pairs() -> None:
    seen: set[tuple[str, str]] = set()
    for route in _http_routes():
        for method in route.methods or set():
            key = (method, route.path)
            assert key not in seen, f"duplicate route {key}"
            seen.add(key)


def test_anonymous_requests_are_rejected_everywhere(anon_client: TestClient) -> None:
    """Every non-public endpoint must 401/403 an unauthenticated caller —
    including error-shape safety (no stack traces, no internals)."""
    for route in _http_routes():
        if route.path in PUBLIC_PATHS or route.path.startswith(LOCAL_ONLY_PREFIXES):
            continue
        for method in sorted(route.methods or set()):
            if method in ("HEAD", "OPTIONS"):
                continue
            response = anon_client.request(method, _dummy_path(route.path))
            assert response.status_code in (401, 403), (
                f"{method} {route.path} answered {response.status_code} "
                "to an anonymous request — expected 401/403"
            )
            body = response.text.lower()
            assert "traceback" not in body and "sqlalchemy" not in body


def test_public_allowlist_is_actually_wired(anon_client: TestClient) -> None:
    response = anon_client.get("/api/v1/utils/health-check/")
    assert response.status_code == 200
    assert anon_client.get("/api/v1/metrics").status_code == 200


def test_responses_carry_request_correlation_id(anon_client: TestClient) -> None:
    """Every response is traceable end-to-end (API-014)."""
    response = anon_client.get("/api/v1/utils/health-check/")
    assert response.headers.get("X-Request-ID")
    echoed = anon_client.get(
        "/api/v1/utils/health-check/", headers={"X-Request-ID": "trace-me-123"}
    )
    assert echoed.headers.get("X-Request-ID") == "trace-me-123"
    # Malformed inbound IDs (log-injection shaped) are replaced, not echoed.
    hostile = anon_client.get(
        "/api/v1/utils/health-check/", headers={"X-Request-ID": "bad\nid" + "x" * 100}
    )
    assert hostile.headers.get("X-Request-ID") != "bad\nid" + "x" * 100


@pytest.fixture(name="superuser_client")
def superuser_client_fixture(session, engine) -> Generator[TestClient, None, None]:
    from app import crud
    from app.models import UserCreate
    from tests_smartforge.conftest import _client_for

    crud.create_user(
        session=session,
        user_create=UserCreate(
            email="smartforge@futureform.com",
            password="not-a-real-password-1",
            full_name="Sandbox Superuser",
            is_superuser=True,
        ),
    )
    yield _client_for(engine, "smartforge@futureform.com")
    app.dependency_overrides.clear()


def test_every_parameterless_get_is_healthy(superuser_client: TestClient) -> None:
    """Wiring/lifecycle smoke over seeded sandbox data: no parameterless GET
    may 500. 503 is allowed ONLY for the data-platform routes, whose stores
    are legitimately unprovisioned in this harness (documented degraded
    mode, surfaced as unavailable — never as silent success)."""
    degraded_ok = ("/api/v1/lake", "/api/v1/warehouse", "/api/v1/platform")
    for route in _http_routes():
        if "{" in route.path or "GET" not in (route.methods or set()):
            continue
        if route.path.startswith(LOCAL_ONLY_PREFIXES):
            continue
        response = superuser_client.get(route.path)
        # 403 = the route is wired and enforcing a DIFFERENT role scope
        # (e.g. /customer/* rejects internal users). Positive-path access is
        # covered per-router in the rest of this suite.
        allowed = {200, 400, 403, 422}
        if route.path.startswith(degraded_ok):
            allowed.add(503)
        # /platform/seed/plan legitimately 404s when the warehouse IS
        # reachable (e.g. a developer's compose stack) but no seed plan has
        # been proposed — a healthy empty state, not a wiring error.
        if route.path == "/api/v1/platform/seed/plan":
            allowed.add(404)
        assert response.status_code in allowed, (
            f"GET {route.path} -> {response.status_code}: {response.text[:200]}"
        )
