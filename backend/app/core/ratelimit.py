"""Identity-aware application rate limiting (API-017 / SEC-012).

Token-bucket limiter keyed by caller identity, layered ON TOP of Traefik's
coarse per-IP limit at ingress: behind one proxy IP a heavy analytical
client must not be able to degrade everyone else, so authenticated callers
get their own bucket per user with a role-based budget.

Tiers (per-minute budgets, env-tunable via RATE_LIMIT_* settings):
  * ``superuser``  — highest budget (admin tooling, bulk operations);
  * ``internal``   — staff roles (operator/maintenance/planner/admin);
  * ``customer``   — lowest authenticated budget (portal accounts);
  * ``anonymous``  — per-client-IP, strictest (unauthenticated traffic).

Tier resolution never touches the database: the bearer JWT is decoded with
the same SECRET_KEY/ALGORITHM as app.core.security and the ``role`` /
``is_superuser`` claims embedded at login are read directly. Any decode
failure (missing, malformed, expired, bad signature) degrades to
``anonymous``. Tokens minted before the claims existed (valid signature,
no ``role``) degrade to ``customer`` — least privilege for an
authenticated caller whose role is unknown, never a staff budget.

Scope and semantics (deliberate):
  * Buckets are in-memory and PER PROCESS. Effective ceilings multiply by
    the number of backend workers/replicas; Traefik's per-IP limit remains
    the cross-replica coarse bound. This tier only needs to be
    best-effort fairness, not a distributed quota.
  * No Redis on purpose: Redis in this stack is best-effort realtime
    fan-out only (see the scope note in app/core/redis.py) — making
    request admission depend on it would add a hard dependency the rest
    of the app deliberately avoids.
  * Single asyncio event loop per process, so bucket updates need no
    locks; a bounded LRU (``max_entries``) caps memory so spoofed
    client IPs cannot grow the table without bound.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from enum import Enum

import jwt

from app.core import security
from app.core.config import settings

_WINDOW_SECONDS = 60.0
_MAX_ENTRIES = 10_000

# Staff roles mirroring app.api.deps.INTERNAL_ROLES (kept as strings so this
# module never imports models / SQLModel into the hot request path).
_INTERNAL_ROLES = frozenset({"admin", "operator", "maintenance", "planner"})


class Tier(str, Enum):
    superuser = "superuser"
    internal = "internal"
    customer = "customer"
    anonymous = "anonymous"


def limit_for(tier: Tier) -> int:
    """Per-minute budget for a tier, read from live settings each call so
    tests (and operators using env overrides) see changes immediately."""
    return {
        Tier.superuser: settings.RATE_LIMIT_SUPERUSER_PER_MINUTE,
        Tier.internal: settings.RATE_LIMIT_INTERNAL_PER_MINUTE,
        Tier.customer: settings.RATE_LIMIT_CUSTOMER_PER_MINUTE,
        Tier.anonymous: settings.RATE_LIMIT_ANONYMOUS_PER_MINUTE,
    }[tier]


def resolve_identity(authorization: str | None, client_ip: str) -> tuple[str, Tier]:
    """Map a request to a bucket key + tier without any DB access.

    Returns ``("anon:<ip>", anonymous)`` unless a verifiable bearer JWT is
    presented; old-format tokens (no role claims) resolve to ``customer``.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return f"anon:{client_ip}", Tier.anonymous
    token = authorization[7:].strip()
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
    except jwt.PyJWTError:
        # Tampered/expired/foreign token: no identity credit — anonymous.
        return f"anon:{client_ip}", Tier.anonymous
    subject = str(payload.get("sub") or "unknown")
    if payload.get("is_superuser") is True:
        return f"user:{subject}", Tier.superuser
    role = payload.get("role")
    if isinstance(role, str) and role in _INTERNAL_ROLES:
        return f"user:{subject}", Tier.internal
    # Explicit customer role, or a pre-claims token (least privilege).
    return f"user:{subject}", Tier.customer


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated: float
    # Monotonic stamp of the last emitted rate-limited WARNING, so an abusive
    # identity produces one log line per window, not one per request.
    last_warned: float


@dataclass(slots=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    should_log: bool


class RateLimiter:
    """In-memory token buckets with LRU eviction (single-loop, lock-free)."""

    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        self._max_entries = max_entries
        self._buckets: dict[str, _Bucket] = {}

    def __len__(self) -> int:
        return len(self._buckets)

    def __contains__(self, key: str) -> bool:
        return key in self._buckets

    def reset(self) -> None:
        """Drop all buckets (test isolation helper)."""
        self._buckets.clear()

    def check(
        self, key: str, limit_per_minute: int, now: float | None = None
    ) -> Decision:
        """Consume one token from ``key``'s bucket; refill on elapsed time."""
        now = time.monotonic() if now is None else now
        rate = limit_per_minute / _WINDOW_SECONDS  # tokens per second
        # LRU: pop + reinsert keeps actively-used keys away from eviction.
        bucket = self._buckets.pop(key, None)
        if bucket is None:
            if len(self._buckets) >= self._max_entries:
                # Evict the least-recently-used bucket (first insertion-order
                # key) so spoofed anonymous IPs cannot grow memory unbounded.
                del self._buckets[next(iter(self._buckets))]
            bucket = _Bucket(
                tokens=float(limit_per_minute), updated=now, last_warned=-math.inf
            )
        else:
            elapsed = max(0.0, now - bucket.updated)
            bucket.tokens = min(float(limit_per_minute), bucket.tokens + elapsed * rate)
            bucket.updated = now
        self._buckets[key] = bucket

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return Decision(
                allowed=True,
                limit=limit_per_minute,
                remaining=int(bucket.tokens),
                retry_after=0,
                should_log=False,
            )
        retry_after = math.ceil((1.0 - bucket.tokens) / rate)
        should_log = (now - bucket.last_warned) >= _WINDOW_SECONDS
        if should_log:
            bucket.last_warned = now
        return Decision(
            allowed=False,
            limit=limit_per_minute,
            remaining=0,
            retry_after=retry_after,
            should_log=should_log,
        )


# Process-wide limiter shared by the middleware (one per worker; see the
# per-process semantics note in the module docstring).
limiter = RateLimiter()
