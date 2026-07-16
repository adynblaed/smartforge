"""Pipeline performance metrics: Prometheus instruments + per-run KPIs.

Answers the operator questions directly and in standard vocabulary
(OBS-008/PERF-*): "we migrated N rows across N tables from omega in Z
seconds at R rows/s and B Mbps — S% success". Three layers, all
non-blocking (in-memory instrument updates + one summary log line per run;
nothing here ever performs I/O on the hot path):

  * Counters/histograms in `PIPELINE_REGISTRY` following Prometheus naming
    conventions (base units: seconds/bytes; `_total` counters) — rates and
    percentiles come from PromQL (`rate(smartforge_pipeline_bytes_total[5m])`
    is the live data-bandwidth signal).
  * Last-run convenience gauges so a Grafana stat panel can show the most
    recent migration's KPIs without PromQL gymnastics.
  * `PipelineRunStats` — aggregates one run, emits the summary line, and
    returns a JSON-safe KPI block that run results (CLI output, control
    tables' `detail`) carry verbatim.

Exposure: the API serves this registry at GET /api/v1/metrics alongside the
factory exporter; the long-lived platform-worker serves its own scrape
endpoint (PLATFORM_METRICS_PORT). Ephemeral CLI runs are recorded by the
summary log line and the control tables — the durable system of record.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

PIPELINE_REGISTRY = CollectorRegistry()

# Wall-time buckets sized for table syncs (sub-second lookups to
# multi-minute large-table seeds).
_STAGE_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600)
_RUN_BUCKETS = (0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1800, 3600)

TABLE_SYNCS = Counter(
    "smartforge_pipeline_table_syncs_total",
    "Table replication attempts by outcome",
    ["table", "kind", "status"],
    registry=PIPELINE_REGISTRY,
)
ROWS_PROCESSED = Counter(
    "smartforge_pipeline_rows_total",
    "Rows replicated source -> lake -> warehouse",
    ["table", "kind"],
    registry=PIPELINE_REGISTRY,
)
BYTES_PROCESSED = Counter(
    "smartforge_pipeline_bytes_total",
    "Published Parquet bytes replicated (compressed, on-disk)",
    ["table", "kind"],
    registry=PIPELINE_REGISTRY,
)
STAGE_DURATION = Histogram(
    "smartforge_pipeline_stage_duration_seconds",
    "Wall time per pipeline stage (extract_stage, publish, warehouse_load, "
    "reconcile, dbt_*)",
    ["table", "stage"],
    buckets=_STAGE_BUCKETS,
    registry=PIPELINE_REGISTRY,
)
RUN_DURATION = Histogram(
    "smartforge_pipeline_run_duration_seconds",
    "Wall time per pipeline run",
    ["kind"],
    buckets=_RUN_BUCKETS,
    registry=PIPELINE_REGISTRY,
)
RUNS = Counter(
    "smartforge_pipeline_runs_total",
    "Pipeline runs by outcome",
    ["kind", "status"],
    registry=PIPELINE_REGISTRY,
)
# Tick-level failures that never reach a recorded run (lock connection
# errors, config failures): the scheduler swallows them to stay alive, so
# they must surface here instead of only in logs (OBS-003 complement).
SCHEDULER_TICK_FAILURES = Counter(
    "smartforge_pipeline_scheduler_tick_failures_total",
    "Dispatcher ticks that raised before a run could be recorded",
    registry=PIPELINE_REGISTRY,
)

# Last-run KPI gauges (one Grafana stat panel each; no PromQL required).
_LAST = {
    "timestamp": Gauge(
        "smartforge_pipeline_last_run_timestamp_seconds",
        "Unix time the last run finished",
        ["kind"],
        registry=PIPELINE_REGISTRY,
    ),
    "duration": Gauge(
        "smartforge_pipeline_last_run_duration_seconds",
        "Wall time of the last run",
        ["kind"],
        registry=PIPELINE_REGISTRY,
    ),
    "rows": Gauge(
        "smartforge_pipeline_last_run_rows",
        "Rows replicated by the last run",
        ["kind"],
        registry=PIPELINE_REGISTRY,
    ),
    "bytes": Gauge(
        "smartforge_pipeline_last_run_bytes",
        "Published Parquet bytes of the last run",
        ["kind"],
        registry=PIPELINE_REGISTRY,
    ),
    "tables": Gauge(
        "smartforge_pipeline_last_run_tables",
        "Tables attempted by the last run",
        ["kind"],
        registry=PIPELINE_REGISTRY,
    ),
    "rows_per_second": Gauge(
        "smartforge_pipeline_last_run_rows_per_second",
        "Row throughput of the last run",
        ["kind"],
        registry=PIPELINE_REGISTRY,
    ),
    "bytes_per_second": Gauge(
        "smartforge_pipeline_last_run_bytes_per_second",
        "Data throughput of the last run (published Parquet bytes/s)",
        ["kind"],
        registry=PIPELINE_REGISTRY,
    ),
    "success_ratio": Gauge(
        "smartforge_pipeline_last_run_success_ratio",
        "Succeeded tables / attempted tables of the last run (0-1)",
        ["kind"],
        registry=PIPELINE_REGISTRY,
    ),
}


@contextmanager
def stage_timer(table: str, stage: str) -> Iterator[None]:
    """Time one pipeline stage; duration is recorded even when the stage
    raises, so failure latency is never invisible."""
    started = time.perf_counter()
    try:
        yield
    finally:
        STAGE_DURATION.labels(table=table, stage=stage).observe(
            time.perf_counter() - started
        )


def format_bytes(value: float) -> str:
    """IEC units, SRE-standard (KiB/MiB/GiB)."""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{value:.0f} B"
        value /= 1024
    return f"{value:.1f} TiB"  # pragma: no cover - loop always returns


def megabits_per_second(byte_count: float, seconds: float) -> float:
    """Network-convention bandwidth (decimal megabits per second)."""
    if seconds <= 0:
        return 0.0
    return byte_count * 8 / 1_000_000 / seconds


class PipelineRunStats:
    """Aggregates one pipeline run into the standard migration KPI block."""

    def __init__(self, kind: str, *, source: str = "omega") -> None:
        self.kind = kind
        self.source = source
        self._started = time.perf_counter()
        self.started_at = dt.datetime.now(dt.timezone.utc)
        self.tables_succeeded = 0
        self.tables_failed = 0
        self.rows = 0
        self.bytes = 0

    def record_table(
        self, table: str, *, rows: int = 0, size_bytes: int = 0, succeeded: bool = True
    ) -> None:
        status = "succeeded" if succeeded else "failed"
        TABLE_SYNCS.labels(table=table, kind=self.kind, status=status).inc()
        if succeeded:
            self.tables_succeeded += 1
            self.rows += rows
            self.bytes += size_bytes
            ROWS_PROCESSED.labels(table=table, kind=self.kind).inc(rows)
            BYTES_PROCESSED.labels(table=table, kind=self.kind).inc(size_bytes)
        else:
            self.tables_failed += 1

    @property
    def tables_total(self) -> int:
        return self.tables_succeeded + self.tables_failed

    def finish(self) -> dict[str, Any]:
        """Close the run: instruments, gauges, ONE summary log line, and the
        JSON-safe KPI block for the run result."""
        duration = max(time.perf_counter() - self._started, 1e-9)
        status = "succeeded" if self.tables_failed == 0 else "failed"
        success_ratio = (
            self.tables_succeeded / self.tables_total if self.tables_total else 1.0
        )
        rows_per_second = self.rows / duration
        bytes_per_second = self.bytes / duration

        RUNS.labels(kind=self.kind, status=status).inc()
        RUN_DURATION.labels(kind=self.kind).observe(duration)
        _LAST["timestamp"].labels(kind=self.kind).set_to_current_time()
        _LAST["duration"].labels(kind=self.kind).set(duration)
        _LAST["rows"].labels(kind=self.kind).set(self.rows)
        _LAST["bytes"].labels(kind=self.kind).set(self.bytes)
        _LAST["tables"].labels(kind=self.kind).set(self.tables_total)
        _LAST["rows_per_second"].labels(kind=self.kind).set(rows_per_second)
        _LAST["bytes_per_second"].labels(kind=self.kind).set(bytes_per_second)
        _LAST["success_ratio"].labels(kind=self.kind).set(success_ratio)

        kpis: dict[str, Any] = {
            "kind": self.kind,
            "source": self.source,
            "started_at": self.started_at.isoformat(),
            "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "duration_seconds": round(duration, 3),
            "tables_total": self.tables_total,
            "tables_succeeded": self.tables_succeeded,
            "tables_failed": self.tables_failed,
            "rows": self.rows,
            "bytes": self.bytes,
            "bytes_human": format_bytes(self.bytes),
            "rows_per_second": round(rows_per_second, 1),
            "throughput_mibps": round(bytes_per_second / (1024 * 1024), 3),
            "throughput_megabits_per_second": round(
                megabits_per_second(self.bytes, duration), 3
            ),
            "success_rate_percent": round(success_ratio * 100, 1),
        }
        # The one-line migration KPI summary (OBS-008): grep-able,
        # dashboard-independent, never carries data values.
        logger.info(
            "pipeline %s complete: %d/%d tables, %s rows, %s in %.2fs — "
            "%.0f rows/s, %.2f Mbps, success %.1f%% (source=%s)",
            self.kind,
            self.tables_succeeded,
            self.tables_total,
            f"{self.rows:,}",
            kpis["bytes_human"],
            duration,
            rows_per_second,
            kpis["throughput_megabits_per_second"],
            kpis["success_rate_percent"],
            self.source,
        )
        return kpis
