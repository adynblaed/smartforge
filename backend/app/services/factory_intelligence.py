"""Factory intelligence: OEE, vision inspection verdicts, defect/scrap analytics (Module 2)."""

from __future__ import annotations

import uuid

from sqlmodel import Session, select

from app.core.config import settings
from app.models import Inspection, OeeMetric, ProductionRun

# Cost assumptions — env-overridable via settings.
SCRAP_UNIT_COST = settings.SCRAP_UNIT_COST
REWORK_UNIT_COST = settings.REWORK_UNIT_COST
DEFECT_TYPES = ["surface_scratch", "dimension_out_of_tol", "porosity", "burr", "none"]


def vision_verdict(part_id: str) -> tuple[bool, str, float]:
    """Deterministic placeholder vision model: stable per part_id (no RNG)."""
    h = sum(ord(c) for c in part_id)
    defect = (h % 5) != 0  # ~80% pass
    dtype = DEFECT_TYPES[h % len(DEFECT_TYPES)] if defect else "none"
    confidence = 0.7 + (h % 30) / 100.0
    return defect, dtype, round(min(0.99, confidence), 2)


def compute_oee_from_run(run: ProductionRun) -> OeeMetric:
    """OEE = Availability × Performance × Quality (spec §2B)."""
    planned_min = max(1.0, run.planned_units * 1.0)  # 1 min/unit nominal
    run_time = max(1.0, planned_min - run.downtime_minutes)
    availability = max(0.0, min(1.0, run_time / planned_min))
    performance = (
        max(0.0, min(1.0, run.actual_units / run.planned_units))
        if run.planned_units
        else 0.0
    )
    good = max(0, run.actual_units - run.scrap_units - run.rework_units)
    quality = good / run.actual_units if run.actual_units else 0.0
    oee = round(availability * performance * quality, 4)
    scrap_rate = run.scrap_units / run.actual_units if run.actual_units else 0.0
    rework_rate = run.rework_units / run.actual_units if run.actual_units else 0.0
    return OeeMetric(
        line_id=run.line_id,
        machine_id=run.machine_id,
        shift=run.shift,
        availability=round(availability, 4),
        performance=round(performance, 4),
        quality=round(quality, 4),
        oee=oee,
        throughput=float(run.actual_units),
        downtime_minutes=run.downtime_minutes,
        scrap_rate=round(scrap_rate, 4),
        rework_rate=round(rework_rate, 4),
    )


def defect_rate(session: Session, line_id: uuid.UUID | None = None) -> float:
    stmt = select(Inspection)
    if line_id:
        stmt = stmt.where(Inspection.line_id == line_id)
    rows = list(session.exec(stmt).all())
    if not rows:
        return 0.0
    return round(sum(1 for r in rows if r.defect_detected) / len(rows), 4)


def scrap_cost_estimate(scrap_units: int, rework_units: int) -> float:
    return round(scrap_units * SCRAP_UNIT_COST + rework_units * REWORK_UNIT_COST, 2)
