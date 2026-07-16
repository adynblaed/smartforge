"""Role-aware application rate limiting (API-017/SEC-012).

Covers tier resolution from real JWTs (no DB), per-IP anonymous bucketing,
429 semantics (Retry-After + X-RateLimit-* headers, one WARNING per window),
exemptions, the disabled-flag bypass, LRU eviction, and that the login flow
still mints working tokens carrying the new claims.
"""

import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core import ratelimit
from app.core.config import settings
from app.core.ratelimit import RateLimiter, Tier, resolve_identity
from app.core.security import create_access_token
from app.main import app

# A path that reaches the middleware but resolves without any dependency
# (404s in the router) — rate limiting must apply before routing concerns.
PROBE_PATH = "/api/v1/this-route-does-not-exist"


@pytest.fixture(autouse=True)
def _fresh_limiter():
    """Isolate bucket state per test."""
    ratelimit.limiter.reset()
    yield
    ratelimit.limiter.reset()


@pytest.fixture
def enabled(monkeypatch):
    """Turn the limiter on with tiny, fast-to-exhaust budgets."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_SUPERUSER_PER_MINUTE", 6)
    monkeypatch.setattr(settings, "RATE_LIMIT_INTERNAL_PER_MINUTE", 5)
    monkeypatch.setattr(settings, "RATE_LIMIT_CUSTOMER_PER_MINUTE", 4)
    monkeypatch.setattr(settings, "RATE_LIMIT_ANONYMOUS_PER_MINUTE", 2)


@pytest.fixture
def client():
    # No dependency overrides: the middleware never touches the DB.
    return TestClient(app)


def _token(**claims) -> str:
    return create_access_token("user-1", timedelta(minutes=5), **claims)


class TestTierResolution:
    def test_superuser_claim_wins(self):
        key, tier = resolve_identity(
            f"Bearer {_token(role='admin', is_superuser=True)}", "1.2.3.4"
        )
        assert tier is Tier.superuser
        assert key == "user:user-1"

    @pytest.mark.parametrize("role", ["admin", "operator", "maintenance", "planner"])
    def test_internal_roles(self, role):
        _, tier = resolve_identity(f"Bearer {_token(role=role)}", "1.2.3.4")
        assert tier is Tier.internal

    def test_customer_role(self):
        _, tier = resolve_identity(f"Bearer {_token(role='customer')}", "1.2.3.4")
        assert tier is Tier.customer

    def test_old_format_token_degrades_to_customer(self):
        """Pre-claims tokens are authenticated but role-unknown: least
        privilege means the customer budget, never a staff one."""
        key, tier = resolve_identity(f"Bearer {_token()}", "1.2.3.4")
        assert tier is Tier.customer
        assert key == "user:user-1"

    def test_missing_header_is_anonymous_per_ip(self):
        key, tier = resolve_identity(None, "10.0.0.9")
        assert (key, tier) == ("anon:10.0.0.9", Tier.anonymous)

    def test_garbage_token_is_anonymous(self):
        key, tier = resolve_identity("Bearer not-a-jwt", "10.0.0.9")
        assert (key, tier) == ("anon:10.0.0.9", Tier.anonymous)

    def test_expired_token_is_anonymous(self):
        expired = create_access_token(
            "user-1", timedelta(minutes=-5), role="admin", is_superuser=True
        )
        _, tier = resolve_identity(f"Bearer {expired}", "10.0.0.9")
        assert tier is Tier.anonymous


class TestEnforcement:
    def test_429_with_retry_after_and_headers(self, enabled, client):
        for _ in range(2):  # anonymous budget = 2/min
            ok = client.get(PROBE_PATH)
            assert ok.status_code == 404
            assert ok.headers["X-RateLimit-Limit"] == "2"
        limited = client.get(PROBE_PATH)
        assert limited.status_code == 429
        body = limited.json()
        assert body["detail"] == "Rate limit exceeded"
        assert body["request_id"]  # correlation middleware ran first
        assert limited.headers["X-RateLimit-Limit"] == "2"
        assert limited.headers["X-RateLimit-Remaining"] == "0"
        assert int(limited.headers["Retry-After"]) >= 1

    def test_remaining_header_counts_down(self, enabled, client):
        remaining = [
            int(client.get(PROBE_PATH).headers["X-RateLimit-Remaining"])
            for _ in range(2)
        ]
        assert remaining == [1, 0]

    def test_anonymous_bucketed_per_client_ip(self, enabled, client):
        for _ in range(2):
            client.get(PROBE_PATH, headers={"X-Forwarded-For": "10.1.1.1"})
        assert (
            client.get(PROBE_PATH, headers={"X-Forwarded-For": "10.1.1.1"}).status_code
            == 429
        )
        # A different client IP has its own untouched bucket.
        other = client.get(PROBE_PATH, headers={"X-Forwarded-For": "10.2.2.2"})
        assert other.status_code == 404
        assert other.headers["X-RateLimit-Remaining"] == "1"

    def test_tier_budget_selected_from_token(self, enabled, client):
        internal = client.get(
            PROBE_PATH, headers={"Authorization": f"Bearer {_token(role='operator')}"}
        )
        assert internal.headers["X-RateLimit-Limit"] == "5"
        superuser = client.get(
            PROBE_PATH,
            headers={
                "Authorization": f"Bearer {_token(role='admin', is_superuser=True)}"
            },
        )
        assert superuser.headers["X-RateLimit-Limit"] == "6"
        old_format = client.get(
            PROBE_PATH, headers={"Authorization": f"Bearer {_token()}"}
        )
        assert old_format.headers["X-RateLimit-Limit"] == "4"  # customer budget

    def test_one_warning_per_identity_per_window(self, enabled, client, caplog):
        for _ in range(2):
            client.get(PROBE_PATH)
        with caplog.at_level(logging.WARNING, logger="smartforge"):
            assert client.get(PROBE_PATH).status_code == 429
            assert client.get(PROBE_PATH).status_code == 429
        warnings = [
            r for r in caplog.records if "rate limit exceeded" in r.getMessage()
        ]
        assert len(warnings) == 1
        assert "tier=anonymous" in warnings[0].getMessage()

    def test_health_check_exempt(self, enabled, client):
        for _ in range(3):  # exhaust the anonymous budget
            client.get(PROBE_PATH)
        response = client.get("/api/v1/utils/health-check/")
        assert response.status_code == 200
        assert "X-RateLimit-Limit" not in response.headers

    def test_options_exempt(self, enabled, client):
        for _ in range(3):
            client.get(PROBE_PATH)
        assert client.options(PROBE_PATH).status_code != 429

    def test_disabled_flag_bypasses(self, client):
        # conftest defaults RATE_LIMIT_ENABLED=False for every suite.
        assert settings.RATE_LIMIT_ENABLED is False
        for _ in range(10):
            response = client.get(PROBE_PATH)
            assert response.status_code == 404
            assert "X-RateLimit-Limit" not in response.headers


class TestBucketEviction:
    def test_lru_eviction_caps_entries(self):
        limiter = RateLimiter(max_entries=3)
        for i in range(3):
            limiter.check(f"anon:10.0.0.{i}", 30, now=float(i))
        # Touch the oldest so it becomes most-recently-used.
        limiter.check("anon:10.0.0.0", 30, now=10.0)
        limiter.check("anon:10.0.0.99", 30, now=11.0)  # forces one eviction
        assert len(limiter) == 3
        assert "anon:10.0.0.1" not in limiter  # true LRU victim
        assert "anon:10.0.0.0" in limiter
        assert "anon:10.0.0.99" in limiter

    def test_refill_on_elapsed_time(self):
        limiter = RateLimiter()
        assert limiter.check("k", 60, now=0.0).allowed
        for _ in range(59):
            limiter.check("k", 60, now=0.0)
        denied = limiter.check("k", 60, now=0.0)
        assert not denied.allowed
        assert denied.retry_after == 1  # 60/min refills 1 token per second
        assert limiter.check("k", 60, now=2.0).allowed  # refilled


def test_login_flow_issues_working_tiered_tokens(internal_client):
    """End-to-end: the real login route mints a token whose claims resolve
    to the caller's tier without any DB access."""
    response = internal_client.post(
        "/api/v1/login/access-token",
        data={
            "username": "operator@smartforge.com",
            "password": settings.SANDBOX_USER_PASSWORD,
        },
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    key, tier = resolve_identity(f"Bearer {token}", "1.2.3.4")
    assert tier is Tier.internal
    assert key.startswith("user:")

    customer = internal_client.post(
        "/api/v1/login/access-token",
        data={
            "username": "buyer@acme-robotics.com",
            "password": settings.SANDBOX_USER_PASSWORD,
        },
    )
    assert customer.status_code == 200
    _, tier = resolve_identity(f"Bearer {customer.json()['access_token']}", "1.2.3.4")
    assert tier is Tier.customer
