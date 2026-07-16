"""Redis client + pub/sub helpers for SmartForge.

Scope (deliberately narrow): real-time fan-out of telemetry and
order-status updates to WebSocket consumers, plus the /services health
probe. There is NO Redis caching or durable queue in this stack — long
work runs in the dedicated worker services (see CLAUDE.md §5), and any
future queue must be a reviewed addition, not an assumption.

All access is resilient: if Redis is unavailable the helpers degrade
gracefully (the API still works via polling) and the degradation is
logged once per outage, never per message.
"""

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Pub/sub channel names — every channel here has BOTH a producer and a
# consumer (telemetry: simulator/machines-route -> /ws/telemetry;
# orders: simulator -> /ws/orders). Don't add speculative channels.
TELEMETRY_CHANNEL = "smartforge:telemetry"
ORDERS_CHANNEL = "smartforge:orders"

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Return a lazily-created async Redis client (connection pooled)."""
    global _client
    if _client is None:
        # redis-py's asyncio from_url is untyped in the shipped stubs.
        _client = aioredis.from_url(  # type: ignore[no-untyped-call]
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
    return _client


# Publish-outage state: warn once when Redis drops, once when it recovers —
# per-message logging would flood at simulator cadence during an outage.
_publish_degraded = False


async def publish(channel: str, payload: dict[str, Any]) -> None:
    """Publish a JSON message; swallow connection errors so callers never break."""
    global _publish_degraded
    try:
        client = get_redis()
        await client.publish(channel, json.dumps(payload, default=str))
    except Exception:
        # Redis is best-effort for real-time; polling fallback covers
        # correctness — but the degradation must be visible to operators.
        if not _publish_degraded:
            _publish_degraded = True
            logger.warning(
                "redis publish failing (channel=%s); realtime updates degraded "
                "to polling until Redis recovers",
                channel,
                exc_info=True,
            )
    else:
        if _publish_degraded:
            _publish_degraded = False
            logger.info("redis publish recovered (channel=%s)", channel)


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
