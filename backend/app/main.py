import asyncio
import contextlib
import logging
import re
import uuid
from collections.abc import AsyncIterator

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.main import api_router
from app.core import ratelimit
from app.core.config import settings
from app.core.logging_config import setup_logging

setup_logging()

_IS_PROD = settings.ENVIRONMENT == "production"
logger = logging.getLogger("smartforge")


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start the in-process telemetry simulator unless disabled (a dedicated
    compose `worker` service can run it instead)."""
    task: asyncio.Task[None] | None = None
    if settings.SIMULATOR_ENABLED:
        from app.workers.telemetry_simulator import run_forever

        task = asyncio.create_task(run_forever())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",  # v1.0.0 LTS — keep in step with pyproject/Chart.appVersion
    # Disable interactive docs + schema in production (avoid API surface disclosure).
    openapi_url=None if _IS_PROD else f"{settings.API_V1_STR}/openapi.json",
    docs_url=None if _IS_PROD else "/docs",
    redoc_url=None if _IS_PROD else "/redoc",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

# Reject requests with an unexpected Host header (Host-header injection / cache
# poisoning). "*" (default) is a no-op for local/CI; set ALLOWED_HOSTS in prod.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)
# Transparent response compression.
app.add_middleware(GZipMiddleware, minimum_size=512)

# Set all CORS enabled origins — restrict methods + headers (no wildcards).
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
        max_age=600,
    )


# Paths exempt from app-layer rate limiting: liveness probes and the
# Prometheus scraper must never be throttled (they run on tight intervals
# and their failure looks like an outage).
_RATE_LIMIT_EXEMPT_PATHS = frozenset(
    {
        f"{settings.API_V1_STR}/utils/health-check/",
        f"{settings.API_V1_STR}/metrics",
    }
)


# NOTE: Starlette executes the LAST-registered "http" middleware first, so
# this limiter is registered FIRST to run innermost — i.e. AFTER the
# request-correlation middleware below, which is what puts request_id on
# request.state for the 429 body.
@app.middleware("http")
async def rate_limit(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Role-aware app-layer rate limiting (API-017/SEC-012).

    Tiers callers by the role claims in their bearer JWT (no DB hit) and
    enforces per-identity token buckets — Traefik's coarse per-IP limit at
    ingress cannot distinguish users behind one proxy IP. Per-process
    semantics and tier budgets: app/core/ratelimit.py.
    """
    if (
        not settings.RATE_LIMIT_ENABLED
        or request.method == "OPTIONS"
        or request.url.path in _RATE_LIMIT_EXEMPT_PATHS
        or request.headers.get("upgrade", "").lower() == "websocket"
    ):
        return await call_next(request)
    # Anonymous callers are bucketed per client IP; behind Traefik the peer
    # address is the proxy, so honor the first X-Forwarded-For hop. Spoofed
    # values only fragment the ANONYMOUS budget (strictest tier) and the
    # limiter's LRU cap bounds memory.
    forwarded = request.headers.get("X-Forwarded-For", "")
    client_ip = forwarded.split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )
    key, tier = ratelimit.resolve_identity(
        request.headers.get("Authorization"), client_ip
    )
    limit = ratelimit.limit_for(tier)
    decision = ratelimit.limiter.check(key, limit)
    if not decision.allowed:
        request_id = getattr(request.state, "request_id", "-")
        if decision.should_log:
            # One WARNING per identity per window — never per request.
            logger.warning(
                "rate limit exceeded tier=%s key=%s limit_per_minute=%d "
                "retry_after_s=%d request_id=%s",
                tier.value,
                key,
                limit,
                decision.retry_after,
                request_id,
            )
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded", "request_id": request_id},
            headers={
                "Retry-After": str(decision.retry_after),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": "0",
            },
        )
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(decision.limit)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Defense-in-depth security headers at the app layer (nginx sets them too)."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
    )
    if request.url.scheme == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


# Correlation IDs must stay log-safe: bounded length, no control characters.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@app.middleware("http")
async def request_correlation_id(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Attach a correlation ID to every request so a call can be traced across
    API logs, query engines, and error reports (API-014). Honors a well-formed
    inbound X-Request-ID from the proxy; otherwise mints one."""
    inbound = request.headers.get("X-Request-ID", "")
    request_id = inbound if _REQUEST_ID_RE.fullmatch(inbound) else uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers.setdefault("X-Request-ID", request_id)
    return response


@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, _exc: Exception) -> JSONResponse:
    """Never leak stack traces / internals to clients on an unhandled error."""
    request_id = getattr(request.state, "request_id", "-")
    logger.exception(
        "Unhandled error on %s %s (request_id=%s)",
        request.method,
        request.url.path,
        request_id,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )


app.include_router(api_router, prefix=settings.API_V1_STR)
