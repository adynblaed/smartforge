"""Seed-plan confirmation gate (confirm-before-seed, mocked state store)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.dataplatform.oracle.metadata import SeedPlan
from app.dataplatform.pipeline import plans
from tests_dataplatform.conftest import FakeEngine, FakeResult, build_inferred


def make_plan(machines_contract, *, blocking: list[str] | None = None) -> SeedPlan:
    return SeedPlan(
        plan_id="plan_20260715T000000Z",
        created_at=dt.datetime(2026, 7, 15, tzinfo=dt.timezone.utc),
        oracle_host="oracle.invalid",
        oracle_service="OMEGAPDB1",
        tables=[build_inferred(machines_contract)],
        blocking_issues=blocking or [],
    )


@pytest.fixture
def stored_plan(machines_contract):
    return make_plan(machines_contract)


def _engine_with_plan(
    monkeypatch, plan: SeedPlan, *, status="proposed", stored_fingerprint=None
):
    fingerprint = stored_fingerprint or plan.fingerprint()

    def responder(sql, _params):
        if "SELECT fingerprint, status, plan" in sql:
            return FakeResult(one=(fingerprint, status, plan.model_dump_json()))
        return None

    engine = FakeEngine(responder)
    monkeypatch.setattr(plans, "loader_engine", lambda: engine)
    return engine


class TestConfirmationPhrase:
    def test_exact_phrase_constant(self):
        assert plans.CONFIRMATION_PHRASE == "SEED OMEGA"

    @pytest.mark.parametrize(
        "phrase",
        ["", "seed omega", "SEED OMEGA ", "SEED-OMEGA", "yes", "SEED  OMEGA"],
    )
    def test_wrong_phrase_rejected_before_any_db_access(
        self, monkeypatch, platform_env, stored_plan, phrase
    ):
        engine = _engine_with_plan(monkeypatch, stored_plan)
        with pytest.raises(plans.PlanNotConfirmedError, match="phrase mismatch"):
            plans.confirm_plan(
                stored_plan.plan_id, stored_plan.fingerprint(), phrase, "tester"
            )
        assert engine.connection.calls == []  # gate closes before the DB


class TestConfirmPlan:
    def test_unknown_plan_id_rejected(self, monkeypatch, platform_env, stored_plan):
        engine = FakeEngine(lambda sql, params: FakeResult(one=None))
        monkeypatch.setattr(plans, "loader_engine", lambda: engine)
        with pytest.raises(plans.PlanNotConfirmedError, match="Unknown seed plan"):
            plans.confirm_plan(
                "plan_ghost", stored_plan.fingerprint(), "SEED OMEGA", "tester"
            )

    def test_wrong_fingerprint_rejected(self, monkeypatch, platform_env, stored_plan):
        _engine_with_plan(monkeypatch, stored_plan)
        with pytest.raises(plans.PlanNotConfirmedError, match="fingerprint mismatch"):
            plans.confirm_plan(
                stored_plan.plan_id, "deadbeefdeadbeef", "SEED OMEGA", "tester"
            )

    def test_already_executed_plan_rejected(
        self, monkeypatch, platform_env, stored_plan
    ):
        _engine_with_plan(monkeypatch, stored_plan, status="executed")
        with pytest.raises(plans.PlanNotConfirmedError, match="already executed"):
            plans.confirm_plan(
                stored_plan.plan_id, stored_plan.fingerprint(), "SEED OMEGA", "tester"
            )

    def test_non_seedable_plan_rejected(
        self, monkeypatch, platform_env, machines_contract
    ):
        blocked = make_plan(
            machines_contract,
            blocking=["OMEGA.MACHINES.GEOM: unmapped type SDO_GEOMETRY"],
        )
        _engine_with_plan(monkeypatch, blocked)
        with pytest.raises(plans.PlanNotConfirmedError, match="blocking issues"):
            plans.confirm_plan(
                blocked.plan_id, blocked.fingerprint(), "SEED OMEGA", "tester"
            )

    def test_correct_fingerprint_and_phrase_confirms(
        self, monkeypatch, platform_env, stored_plan
    ):
        engine = _engine_with_plan(monkeypatch, stored_plan)
        confirmed = plans.confirm_plan(
            stored_plan.plan_id, stored_plan.fingerprint(), "SEED OMEGA", "tester@x"
        )
        assert confirmed.plan_id == stored_plan.plan_id
        assert confirmed.fingerprint() == stored_plan.fingerprint()
        update_sql, update_params = engine.connection.calls[-1]
        assert "SET status = 'confirmed'" in update_sql
        assert update_params["by"] == "tester@x"
        assert update_params["p"] == stored_plan.plan_id


class TestFingerprint:
    def test_fingerprint_stable_and_schema_sensitive(self, machines_contract):
        a = make_plan(machines_contract)
        b = make_plan(machines_contract)
        assert a.fingerprint() == b.fingerprint()

        drifted = make_plan(machines_contract)
        drifted.tables[0].schema_hash = "sha256:different"
        assert drifted.fingerprint() != a.fingerprint()

    def test_is_seedable_requires_tables_and_no_blockers(self, machines_contract):
        assert make_plan(machines_contract).is_seedable
        assert not make_plan(machines_contract, blocking=["x"]).is_seedable
        empty = make_plan(machines_contract)
        empty = empty.model_copy(update={"tables": []})
        assert not empty.is_seedable
