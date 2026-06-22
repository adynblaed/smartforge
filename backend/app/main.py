import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.main import api_router
from app.core.config import settings

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
    task: asyncio.Task | None = None
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


@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Never leak stack traces / internals to clients on an unhandled error."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(api_router, prefix=settings.API_V1_STR)
