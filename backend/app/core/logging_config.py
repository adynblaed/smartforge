"""Central logging configuration for every SmartForge process.

One deliberate setup shared by the API (app.main), the telemetry worker,
the data-platform scheduler, and the operator CLI — replacing scattered
`logging.basicConfig` import side effects. Guarantees:

  * one timestamped, name-carrying line format across all services, so
    compose/k8s log aggregation reads identically everywhere (OBS-004);
  * app loggers actually emit at INFO (route telemetry lines, pipeline
    stage logs) instead of depending on a third-party side effect;
  * level is operator-tunable via LOG_LEVEL without code changes.

Payload safety (OBS-006) stays the callers' contract: log lines carry
identifiers and counts, never query literals, tokens, or row payloads.
"""

from __future__ import annotations

import logging
import os

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_logging(*, level: str | None = None) -> None:
    """Configure root logging once per process (idempotent via force=True).

    `level` overrides the LOG_LEVEL env var (default INFO). Invalid names
    fall back to INFO rather than failing process start.
    """
    chosen = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    numeric = getattr(logging, chosen, None)
    if not isinstance(numeric, int):
        numeric = logging.INFO
    logging.basicConfig(level=numeric, format=LOG_FORMAT, force=True)
    # Chatty third-party INFO noise stays at WARNING unless explicitly raised.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(max(numeric, logging.WARNING))
