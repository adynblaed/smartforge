"""Unit tests for SmartForge service-layer functions (no HTTP)."""

import uuid

import pytest
from sqlmodel import select

import app.models as m
from app.services import factory_intelligence as fi
from app.services import integrations
from app.services import machine_intelligence as mi
from app.services import supply_chain as sc
from app.services.askai import _fallback_answer, retrieve


def _machine(session) -> m.Machine:
    return session.exec(select(m.Machine)).first()


# ---- Health scoring (1E) ----
def test_health_score_empty_telemetry_uses_machine_score(session):
    machine = _machine(session)
    machine.health_score = 77.0
    score = mi.compute_health_score(machine, [])
    assert score.score == 77.0


def test_health_score_healthy_vs_degraded(session):
    machine = _machine(session)
    healthy = [
        m.TelemetryEvent(machine_id=machine.id, temperature=55, vibration=0.2,
                         line_status=m.LineStatus.running)
        for _ in range(10)
    ]
    degraded = [
        m.TelemetryEvent(machine_id=machine.id, temperature=95, vibration=0.9,
                         fault_code="E1", line_status=m.LineStatus.down)
        for _ in range(10)
    ]
    hs = mi.compute_health_score(machine, healthy).score
    ds = mi.compute_health_score(machine, degraded).score
    assert 0.0 <= ds < hs <= 100.0
    assert hs > 70


def test_health_score_bounded(session):
    machine = _machine(session)
    extreme = [
        m.TelemetryEvent(machine_id=machine.id, temperature=200, vibration=5.0,
                         fault_code="X", line_status=m.LineStatus.down)
        for _ in range(20)
    ]
    score = mi.compute_health_score(machine, extreme).score
    assert score == 0.0  # clamped, never negative


# ---- Alert rules (1B) ----
def test_alert_rules_trigger_and_dedupe(session):
    machine = _machine(session)
    machine.runtime_hours = 5000
    telem = m.TelemetryEvent(machine_id=machine.id, temperature=95, vibration=0.9,
                             fault_code="E101", line_status=m.LineStatus.down,
                             runtime_hours=5000)
    first = mi.evaluate_alerts(session, machine, telem)
    rules = {a.rule for a in first}
    assert {"high_vibration", "rising_temperature", "runtime_threshold",
            "repeated_fault"} <= rules
    # Re-evaluating must not duplicate active alerts.
    second = mi.evaluate_alerts(session, machine, telem)
    assert second == []


def test_draft_work_order_priority_mapping(session):
    machine = _machine(session)
    alert = m.Alert(machine_id=machine.id, rule="repeated_fault",
                    severity=m.Severity.critical, message="x")
    session.add(alert)
    session.commit()
    session.refresh(alert)
    wo = mi.draft_work_order_from_alert(session, alert)
    assert wo.priority == 1
    assert wo.status == m.WorkOrderStatus.draft
    assert wo.source_alert_id == alert.id


# ---- OEE (2B) ----
def test_oee_computation():
    run = m.ProductionRun(line_id=uuid.uuid4(), planned_units=1000,
                          actual_units=900, scrap_units=45, rework_units=20,
                          downtime_minutes=100)
    oee = fi.compute_oee_from_run(run)
    assert 0 <= oee.availability <= 1
    assert 0 <= oee.performance <= 1
    assert 0 <= oee.quality <= 1
    assert oee.oee == pytest.approx(
        oee.availability * oee.performance * oee.quality, rel=1e-3
    )
    assert oee.scrap_rate == pytest.approx(45 / 900, rel=1e-3)


def test_oee_zero_units_no_divide_by_zero():
    run = m.ProductionRun(line_id=uuid.uuid4(), planned_units=0, actual_units=0)
    oee = fi.compute_oee_from_run(run)
    assert oee.oee == 0.0
    assert oee.quality == 0.0


# ---- Vision (2A) ----
def test_vision_verdict_deterministic():
    a = fi.vision_verdict("PART-123")
    b = fi.vision_verdict("PART-123")
    assert a == b
    detected, dtype, conf = a
    assert isinstance(detected, bool)
    assert 0 <= conf <= 1
    if not detected:
        assert dtype == "none"


def test_scrap_cost_estimate():
    assert fi.scrap_cost_estimate(2, 3) == pytest.approx(
        2 * fi.SCRAP_UNIT_COST + 3 * fi.REWORK_UNIT_COST
    )


# ---- Quoting (4B) ----
def test_quote_pricing_and_rush_premium():
    base = sc.price_quote(m.Quote(customer="A", part_type="bracket", quantity=100))
    rush = sc.price_quote(
        m.Quote(customer="A", part_type="bracket", quantity=100, rush=True)
    )
    assert base.estimated_price > 0
    assert 0 < base.margin_estimate < 1
    assert rush.rush_premium > 0
    assert rush.estimated_price > base.estimated_price
    assert rush.timeline_days < base.timeline_days


def test_quote_high_volume_risk_flag():
    q = sc.price_quote(m.Quote(customer="A", part_type="x", quantity=10000))
    assert q.risk_flags and "high_volume_capacity_risk" in q.risk_flags


# ---- AskAI retrieval + fallback (1C) ----
def test_retrieve_returns_relevant_doc(session):
    machine = _machine(session)
    docs = retrieve(session, "cnc mill vibration bearing spindle",
                    machine_id=machine.id)
    assert docs
    assert any("Vibration" in d.title for d in docs)


def test_fallback_answer_includes_question(session):
    docs = retrieve(session, "vibration", machine_id=None)
    out = _fallback_answer("Why is vibration high?", docs, "ctx")
    assert "vibration high" in out.lower()


# ---- Integrations (3A) ----
def test_run_sync_records_events_with_one_failure(session):
    events = integrations.run_sync(session, "erp")
    assert len(events) == len(integrations.ERP_ENTITIES)
    assert any(e.status == m.SyncStatus.failed for e in events)
    status = integrations.integration_status(session)
    assert status.erp.total_events >= len(events)
    assert status.erp.failed_records >= 1


def test_sync_fiix_marks_synced(session):
    machine = _machine(session)
    wo = m.WorkOrder(machine_id=machine.id, fault_type="x",
                     severity=m.Severity.high, recommended_task="t")
    session.add(wo)
    session.commit()
    session.refresh(wo)
    synced = integrations.sync_fiix(session, wo)
    assert synced.fiix_sync_state == m.FiixSyncState.synced
    assert synced.fiix_id
