"""Long-running platform worker (compose service `platform-worker`).

Phase-1 orchestration (Migration §9): a small worker loop that fires the
dispatcher at the top of every hour, UTC. Single-flight is enforced inside
`dispatch()` via a Postgres advisory lock, so an over-running tick can
never overlap the next one. Graduation path: replace this loop with
Dagster/Airflow invoking the same `dispatch()`.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
import signal
import threading

from app.core.logging_config import setup_logging
from app.dataplatform.config import get_platform_settings
from app.dataplatform.metrics import PIPELINE_REGISTRY, SCHEDULER_TICK_FAILURES
from app.dataplatform.pipeline.dispatcher import dispatch

setup_logging()
logger = logging.getLogger("dataplatform.scheduler")


def start_metrics_exporter() -> None:
    """Expose the pipeline metrics registry for Prometheus (OBS-008).

    Non-blocking: prometheus_client serves scrapes from its own daemon
    thread; the dispatch loop never waits on it. Port 0 disables cleanly.
    """
    port = get_platform_settings().PLATFORM_METRICS_PORT
    if not port:
        logger.info("pipeline metrics exporter disabled (PLATFORM_METRICS_PORT=0)")
        return
    from prometheus_client import start_http_server

    start_http_server(port, registry=PIPELINE_REGISTRY)
    logger.info("pipeline metrics exporter listening on :%d/metrics", port)


def seconds_until_next_hour(now: dt.datetime) -> float:
    next_hour = (now + dt.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return (next_hour - now).total_seconds()


# Set by SIGTERM/SIGINT: the loop drains (finishes any in-flight tick,
# skips the next sleep) instead of dying mid-dispatch — a killed tick is
# safe (idempotent merges, watermark untouched) but a drained one is free.
_shutdown = threading.Event()


def _install_signal_handlers() -> None:
    def handle(signum: int, _frame: object) -> None:
        logger.info("received signal %d — draining after current tick", signum)
        _shutdown.set()

    # Signal handlers only work on the main thread (and SIGTERM is not a
    # thing on Windows dev shells) — best effort by design.
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(ValueError, AttributeError, OSError):
            signal.signal(sig, handle)


def run_forever() -> None:
    logger.info("platform worker started (hourly dispatch, UTC)")
    _install_signal_handlers()
    start_metrics_exporter()
    while not _shutdown.is_set():
        now = dt.datetime.now(dt.timezone.utc)
        wait = seconds_until_next_hour(now)
        logger.info("next dispatch in %.0fs", wait)
        if _shutdown.wait(timeout=wait):
            break
        try:
            result = dispatch()
            logger.info("dispatch finished: %s", result.get("status"))
        except Exception:
            # Self-heal by design: swallow, count, and wait for the next
            # tick — a failed window replays safely (idempotent merges,
            # watermark untouched). Fail loud in logs + metrics; the
            # freshness dead-man's switch alerts independently if data age
            # exceeds SLA (OBS-003).
            SCHEDULER_TICK_FAILURES.inc()
            logger.exception("dispatch tick failed")
    logger.info("platform worker stopped cleanly")


if __name__ == "__main__":
    run_forever()
