"""app/core/redis.py helpers — offline (no Redis server ever contacted).

Covers REDIS_URL credential handling, the publish() outage/recovery logging
contract (once per transition, never per message), and the channel-constant
scope rule (every channel has both a producer and a consumer).
"""

import asyncio
import logging

import pytest

import app.core.redis as redis_mod
from app.core.config import Settings

_SETTINGS_KWARGS = {
    "_env_file": None,
    "PROJECT_NAME": "t",
    "POSTGRES_SERVER": "db.invalid",
    "POSTGRES_USER": "x",
    "POSTGRES_PASSWORD": "offline-test-only",
    "POSTGRES_DB": "app",
    "FIRST_SUPERUSER": "a@b.co",
    "FIRST_SUPERUSER_PASSWORD": "offline-test-only",
    "SECRET_KEY": "offline-test-only",
    "SANDBOX_USER_PASSWORD": "offline-test-only",
}


class TestRedisUrl:
    def test_password_included_when_set(self):
        s = Settings(
            **_SETTINGS_KWARGS, REDIS_HOST="r.invalid", REDIS_PASSWORD="s3cret"
        )
        assert s.REDIS_URL == "redis://:s3cret@r.invalid:6379/0"

    def test_no_auth_segment_without_password(self):
        s = Settings(**_SETTINGS_KWARGS, REDIS_HOST="r.invalid", REDIS_PORT=6380)
        assert s.REDIS_URL == "redis://r.invalid:6380/0"


class _FakeClient:
    def __init__(self):
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel, payload):
        self.published.append((channel, payload))


@pytest.fixture
def fresh_publish_state(monkeypatch):
    """Reset the module-level outage latch so tests are order-independent."""
    monkeypatch.setattr(redis_mod, "_publish_degraded", False)
    yield


class TestPublishDegradation:
    def _warnings(self, caplog):
        return [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING
            and "redis publish failing" in r.getMessage()
        ]

    def _recoveries(self, caplog):
        return [
            r
            for r in caplog.records
            if r.levelno == logging.INFO and "redis publish recovered" in r.getMessage()
        ]

    def test_outage_logged_once_then_recovery_then_again(
        self, monkeypatch, caplog, fresh_publish_state
    ):
        def broken():
            raise ConnectionError("redis is down")

        with caplog.at_level(logging.INFO, logger="app.core.redis"):
            # -- outage: first failure warns, second is silent --
            monkeypatch.setattr(redis_mod, "get_redis", broken)
            asyncio.run(redis_mod.publish("chan", {"a": 1}))
            assert len(self._warnings(caplog)) == 1
            asyncio.run(redis_mod.publish("chan", {"a": 2}))
            assert len(self._warnings(caplog)) == 1  # still exactly one

            # -- recovery: exactly one info line --
            client = _FakeClient()
            monkeypatch.setattr(redis_mod, "get_redis", lambda: client)
            asyncio.run(redis_mod.publish("chan", {"a": 3}))
            assert len(self._recoveries(caplog)) == 1
            assert client.published and client.published[0][0] == "chan"

            # -- second outage transition warns again --
            monkeypatch.setattr(redis_mod, "get_redis", broken)
            asyncio.run(redis_mod.publish("chan", {"a": 4}))
            assert len(self._warnings(caplog)) == 2

    def test_publish_swallows_failure(self, monkeypatch, fresh_publish_state):
        def broken():
            raise ConnectionError("redis is down")

        monkeypatch.setattr(redis_mod, "get_redis", broken)
        # Must never raise: callers (routes, simulator) depend on this.
        asyncio.run(redis_mod.publish("chan", {"a": 1}))

    def test_steady_state_success_logs_nothing(
        self, monkeypatch, caplog, fresh_publish_state
    ):
        client = _FakeClient()
        monkeypatch.setattr(redis_mod, "get_redis", lambda: client)
        with caplog.at_level(logging.INFO, logger="app.core.redis"):
            asyncio.run(redis_mod.publish("chan", {"a": 1}))
        assert not self._warnings(caplog)
        assert not self._recoveries(caplog)


class TestChannelScope:
    def test_channels_with_producer_and_consumer_exist(self):
        assert redis_mod.TELEMETRY_CHANNEL == "smartforge:telemetry"
        assert redis_mod.ORDERS_CHANNEL == "smartforge:orders"

    def test_no_speculative_alerts_channel(self):
        # Scope rule: no channel without both a producer and a consumer.
        assert not hasattr(redis_mod, "ALERTS_CHANNEL")
