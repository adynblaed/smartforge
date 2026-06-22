"""Telemetry simulator (spec §1A, §9).

Generates machine telemetry on an interval, recomputes health, raises alerts,
publishes to Redis pub/sub, and updates Prometheus gauges. Runs as a FastAPI
startup task and/or a standalone compose `worker` service.
"""

from __future__ import annotations

import asyncio
import random

from sqlmodel import Session, select

from app.api.routes.command_center import refresh_gauges
from app.core import redis
from app.core.config import settings
from app.core.db import engine
from app.models import (
    CustomerOrder,
    LineStatus,
    Machine,
    MaintenanceState,
    OrderStage,
    TelemetryEvent,
)
from app.services import machine_intelligence

_RNG = random.Random()

# Forward progression of order stages (real-time tracker, spec §5D).
_STAGE_ORDER = [
    OrderStage.received,
    OrderStage.scheduled,
    OrderStage.in_production,
    OrderStage.inspection,
    OrderStage.complete,
    OrderStage.shipped,
]


def _make_telemetry(machine: Machine) -> TelemetryEvent:
    """Produce a plausible reading; occasionally spike to trigger alerts."""
    spike = _RNG.random() < 0.12
    base_temp = 55 + _RNG.uniform(0, 20)
    base_vib = 0.2 + _RNG.uniform(0, 0.25)
    fault = None
    line_status = LineStatus.running
    if spike:
        base_temp += _RNG.uniform(25, 40)
        base_vib += _RNG.uniform(0.3, 0.6)
        if _RNG.random() < 0.5:
            fault = _RNG.choice(["E101", "E205", "OT-12", "VB-09"])
            line_status = LineStatus.down
    return TelemetryEvent(
        machine_id=machine.id,
        temperature=round(base_temp, 1),
        vibration=round(base_vib, 3),
        cycle_time=round(_RNG.uniform(8, 14), 2),
        runtime_hours=round(machine.runtime_hours + _RNG.uniform(0.01, 0.05), 2),
        fault_code=fault,
        power_draw=round(_RNG.uniform(5, 22), 1),
        line_status=line_status,
        maintenance_state=MaintenanceState.ok,
    )


async def _advance_orders(session: Session) -> None:
    """Move one not-yet-shipped order forward a stage and publish the change."""
    open_orders = [
        o
        for o in session.exec(select(CustomerOrder)).all()
        if o.stage != OrderStage.shipped
    ]
    if not open_orders or _RNG.random() > 0.4:
        return
    order = _RNG.choice(open_orders)
    idx = _STAGE_ORDER.index(order.stage)
    order.stage = _STAGE_ORDER[min(idx + 1, len(_STAGE_ORDER) - 1)]
    if order.stage in (OrderStage.complete, OrderStage.shipped):
        order.delayed = False
        order.delay_reason = None
    session.add(order)
    session.commit()
    await redis.publish(redis.ORDERS_CHANNEL, {
        "order_id": str(order.id),
        "order_number": order.order_number,
        "stage": order.stage.value,
        "customer_id": str(order.customer_id),
    })


async def _tick() -> None:
    with Session(engine) as session:
        machines = list(session.exec(select(Machine)).all())
        for machine in machines:
            telemetry = _make_telemetry(machine)
            machine_intelligence.apply_telemetry(session, machine, telemetry)
            await redis.publish(redis.TELEMETRY_CHANNEL, {
                "machine_id": str(machine.id),
                "code": machine.code,
                "health_score": machine.health_score,
                "status": machine.status.value,
                "temperature": telemetry.temperature,
                "vibration": telemetry.vibration,
            })
        await _advance_orders(session)
        refresh_gauges(session)


async def run_forever() -> None:
    interval = settings.SIMULATOR_INTERVAL_SECONDS
    while True:
        try:
            await _tick()
        except Exception:
            # Never let a bad tick kill the loop.
            pass
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(run_forever())
