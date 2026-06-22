"""Redis client + pub/sub helpers for SmartForge.

Used for real-time fan-out of telemetry and order-status updates, caching,
and background-job coordination. All access is resilient: if Redis is
unavailable the helpers degrade gracefully (the API still works via polling).
"""

import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

# Pub/sub channel names
TELEMETRY_CHANNEL = "smartforge:telemetry"
ALERTS_CHANNEL = "smartforge:alerts"
ORDERS_CHANNEL = "smartforge:orders"

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Return a lazily-created async Redis client (connection pooled)."""
    global _client
    if _client is None:
        _client = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
    return _client


async def publish(channel: str, payload: dict[str, Any]) -> None:
    """Publish a JSON message; swallow connection errors so callers never break."""
    try:
        client = get_redis()
        await client.publish(channel, json.dumps(payload, default=str))
    except Exception:
        # Redis is best-effort for real-time; polling fallback covers correctness.
        pass


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
