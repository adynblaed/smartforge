"""Long-running platform worker (compose service `platform-worker`).

Phase-1 orchestration (Migration §9): a small worker loop that fires the
dispatcher at the top of every hour, UTC. Single-flight is enforced inside
`dispatch()` via a Postgres advisory lock, so an over-running tick can
never overlap the next one. Graduation path: replace this loop with
Dagster/Airflow invoking the same `dispatch()`.
"""

from __future__ import annotations

import datetime as dt
import logging
import time

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


def run_forever() -> None:
    logger.info("platform worker started (hourly dispatch, UTC)")
    start_metrics_exporter()
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        wait = seconds_until_next_hour(now)
        logger.info("next dispatch in %.0fs", wait)
        time.sleep(wait)
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


if __name__ == "__main__":
    run_forever()
