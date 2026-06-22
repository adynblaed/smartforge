"""SmartForge custom Prometheus exporter (spec §3B, §8).

Gauges are updated by the telemetry simulator and the aggregation routes, then
scraped at GET /api/v1/metrics. Metric names mirror the spec examples.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Gauge, generate_latest

REGISTRY = CollectorRegistry()

# Per-machine gauges
MACHINE_HEALTH = Gauge(
    "smartforge_machine_health_score",
    "Machine health score (0-100)",
    ["machine_id"],
    registry=REGISTRY,
)
MACHINE_TEMP = Gauge(
    "smartforge_machine_temperature_celsius",
    "Machine temperature (Celsius)",
    ["machine_id"],
    registry=REGISTRY,
)
MACHINE_VIBRATION = Gauge(
    "smartforge_machine_vibration_index",
    "Machine vibration index",
    ["machine_id"],
    registry=REGISTRY,
)

# Per-line gauges
OEE_PERCENT = Gauge(
    "smartforge_oee_percent", "OEE percent by line", ["line_id"], registry=REGISTRY
)
SCRAP_RATE = Gauge(
    "smartforge_scrap_rate_percent",
    "Scrap rate percent by line",
    ["line_id"],
    registry=REGISTRY,
)

# Factory-wide gauges
OPEN_WORK_ORDERS = Gauge(
    "smartforge_open_work_orders_total", "Open work orders", registry=REGISTRY
)
UNPLANNED_DOWNTIME = Gauge(
    "smartforge_unplanned_downtime_minutes_total",
    "Unplanned downtime minutes",
    registry=REGISTRY,
)
ORDERS_DELAYED = Gauge(
    "smartforge_customer_orders_delayed_total",
    "Delayed customer orders",
    registry=REGISTRY,
)
INVENTORY_BELOW_THRESHOLD = Gauge(
    "smartforge_inventory_items_below_threshold_total",
    "Inventory items below reorder threshold",
    registry=REGISTRY,
)


def render_metrics() -> bytes:
    """Render the registry in Prometheus text exposition format."""
    return generate_latest(REGISTRY)
