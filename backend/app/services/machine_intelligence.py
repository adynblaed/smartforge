"""Machine health scoring, alert-rule engine, and work-order drafting (Module 1)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlmodel import Session, col, desc, select

from app.core.config import settings
from app.models import (
    Alert,
    AlertStatus,
    Machine,
    MachineHealthScore,
    MachineStatus,
    Severity,
    TelemetryEvent,
    WorkOrder,
    WorkOrderStatus,
)
from app.models.base import get_datetime_utc

# Thresholds for the rule engine (spec §1B) — env-overridable via settings.
VIBRATION_LIMIT = settings.ALERT_VIBRATION_LIMIT
TEMP_LIMIT = settings.ALERT_TEMP_LIMIT
RUNTIME_LIMIT = settings.ALERT_RUNTIME_LIMIT
HEALTH_FLOOR = settings.ALERT_HEALTH_FLOOR


def compute_health_score(
    machine: Machine, recent: list[TelemetryEvent]
) -> MachineHealthScore:
    """Derive a 0-100 health score from recent telemetry + machine state.

    Factors (spec §1E): fault frequency, runtime hours, vibration/temperature
    trends, missed maintenance, production interruptions.
    """
    if not recent:
        return MachineHealthScore(machine_id=machine.id, score=machine.health_score)

    n = len(recent)
    avg_vibration = sum(t.vibration for t in recent) / n
    avg_temp = sum(t.temperature for t in recent) / n
    fault_count = sum(1 for t in recent if t.fault_code)
    fault_frequency = fault_count / n
    interruptions = sum(1 for t in recent if t.line_status.value in ("down", "idle"))

    score = 100.0
    score -= min(35.0, (avg_vibration / VIBRATION_LIMIT) * 25.0)
    score -= min(25.0, max(0.0, (avg_temp - 60.0) / (TEMP_LIMIT - 60.0)) * 25.0)
    score -= fault_frequency * 30.0
    score -= min(10.0, machine.runtime_hours / RUNTIME_LIMIT * 10.0)
    score -= min(10.0, interruptions / n * 10.0)
    score = max(0.0, round(score, 1))

    downtime_risk = round(min(1.0, (100.0 - score) / 100.0), 2)
    return MachineHealthScore(
        machine_id=machine.id,
        score=score,
        fault_frequency=round(fault_frequency, 3),
        vibration_trend=round(avg_vibration, 3),
        temperature_trend=round(avg_temp, 2),
        production_interruptions=interruptions,
        downtime_risk=downtime_risk,
    )


def _has_recent_active_alert(
    session: Session, machine_id: uuid.UUID, rule: str
) -> bool:
    stmt = select(Alert).where(
        Alert.machine_id == machine_id,
        Alert.rule == rule,
        Alert.status != AlertStatus.resolved,
    )
    return session.exec(stmt).first() is not None


def evaluate_alerts(
    session: Session, machine: Machine, telemetry: TelemetryEvent
) -> list[Alert]:
    """Apply alert rules to fresh telemetry; create alerts (de-duplicated)."""
    new_alerts: list[Alert] = []

    def maybe(
        rule: str, severity: Severity, message: str, action: str, window: str
    ) -> None:
        if _has_recent_active_alert(session, machine.id, rule):
            return
        alert = Alert(
            machine_id=machine.id,
            rule=rule,
            severity=severity,
            message=message,
            recommended_action=action,
            suggested_window=window,
        )
        session.add(alert)
        new_alerts.append(alert)

    if telemetry.vibration > VIBRATION_LIMIT:
        maybe(
            "high_vibration",
            Severity.high,
            f"Vibration {telemetry.vibration:.2f} exceeds {VIBRATION_LIMIT}",
            "Inspect bearings and balance; schedule vibration analysis.",
            "next 24h",
        )
    if telemetry.temperature > TEMP_LIMIT:
        maybe(
            "rising_temperature",
            Severity.high,
            f"Temperature {telemetry.temperature:.1f}°C exceeds {TEMP_LIMIT}°C",
            "Check coolant flow and spindle load; reduce feed rate.",
            "next 12h",
        )
    if machine.runtime_hours > RUNTIME_LIMIT:
        maybe(
            "runtime_threshold",
            Severity.medium,
            f"Runtime {machine.runtime_hours:.0f}h exceeds {RUNTIME_LIMIT:.0f}h",
            "Schedule preventive maintenance service.",
            "next maintenance window",
        )
    if telemetry.fault_code:
        maybe(
            "repeated_fault",
            Severity.critical,
            f"Fault code {telemetry.fault_code} reported",
            "Run diagnostics; consult fault guide via AskAI.",
            "immediate",
        )
    if machine.health_score < HEALTH_FLOOR:
        maybe(
            "low_health_score",
            Severity.high,
            f"Health score {machine.health_score:.0f} below {HEALTH_FLOOR:.0f}",
            "Open predictive maintenance review.",
            "next 48h",
        )
    if new_alerts:
        session.commit()
        for a in new_alerts:
            session.refresh(a)
    return new_alerts


def draft_work_order_from_alert(session: Session, alert: Alert) -> WorkOrder:
    """Generate a work-order draft from a detected fault/alert (spec §1D)."""
    skill_map = {
        "high_vibration": "mechanical",
        "rising_temperature": "thermal/coolant",
        "runtime_threshold": "preventive",
        "repeated_fault": "controls",
        "low_health_score": "diagnostics",
    }
    priority = {Severity.critical: 1, Severity.high: 2, Severity.medium: 3}.get(
        alert.severity, 4
    )
    wo = WorkOrder(
        machine_id=alert.machine_id,
        fault_type=alert.rule,
        severity=alert.severity,
        recommended_task=alert.recommended_action or "Investigate alert",
        required_skill=skill_map.get(alert.rule, "general"),
        suggested_due_date=get_datetime_utc() + timedelta(days=2),
        source_alert_id=alert.id,
        priority=priority,
        status=WorkOrderStatus.draft,
    )
    session.add(wo)
    session.commit()
    session.refresh(wo)
    return wo


def recent_telemetry(
    session: Session, machine_id: uuid.UUID, limit: int = 30
) -> list[TelemetryEvent]:
    stmt = (
        select(TelemetryEvent)
        .where(TelemetryEvent.machine_id == machine_id)
        .order_by(desc(col(TelemetryEvent.created_at)))
        .limit(limit)
    )
    return list(session.exec(stmt).all())


def apply_telemetry(
    session: Session, machine: Machine, telemetry: TelemetryEvent
) -> MachineHealthScore:
    """Persist telemetry, recompute health, update machine snapshot, raise alerts."""
    session.add(telemetry)
    machine.runtime_hours = telemetry.runtime_hours
    machine.last_fault_code = telemetry.fault_code
    machine.maintenance_state = telemetry.maintenance_state
    if telemetry.fault_code:
        machine.status = MachineStatus.fault
    elif telemetry.line_status.value == "running":
        machine.status = MachineStatus.running
    elif telemetry.line_status.value == "maintenance":
        machine.status = MachineStatus.maintenance
    else:
        machine.status = MachineStatus.idle
    session.add(machine)
    session.commit()

    history = recent_telemetry(session, machine.id)
    health = compute_health_score(machine, history)
    session.add(health)
    machine.health_score = health.score
    session.add(machine)
    session.commit()
    session.refresh(machine)
    session.refresh(health)

    evaluate_alerts(session, machine, telemetry)
    auto_draft_work_orders(session, machine.id)
    return health


def auto_draft_work_orders(session: Session, machine_id: uuid.UUID) -> list[WorkOrder]:
    """Draft a work order for each active high/critical alert that lacks one (§1D).

    Idempotent: keyed on source_alert_id so each fault yields at most one draft.
    Drafts still require human approval.
    """
    drafted: list[WorkOrder] = []
    alerts = session.exec(
        select(Alert).where(
            Alert.machine_id == machine_id,
            Alert.status == AlertStatus.active,
            col(Alert.severity).in_([Severity.high, Severity.critical]),
        )
    ).all()
    for alert in alerts:
        exists = session.exec(
            select(WorkOrder).where(WorkOrder.source_alert_id == alert.id)
        ).first()
        if exists is None:
            drafted.append(draft_work_order_from_alert(session, alert))
    return drafted
