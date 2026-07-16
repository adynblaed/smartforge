"""Seed-plan lifecycle: discover -> propose -> confirm -> execute.

Nothing writes target schemas or moves data until an operator has reviewed
the inferred plan and explicitly confirmed it (the SEED gate). Confirmation
requires the exact plan fingerprint, so a stale confirmation can never
execute a different plan than the one reviewed.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

import sqlalchemy as sa

from app.dataplatform.config import get_platform_settings
from app.dataplatform.oracle.connection import oracle_connection, verify_read_only
from app.dataplatform.oracle.metadata import SeedPlan, build_seed_plan
from app.dataplatform.registry import load_registry, load_type_mappings
from app.dataplatform.warehouse.postgres import loader_engine

logger = logging.getLogger(__name__)

CONFIRMATION_PHRASE = "SEED OMEGA"


class PlanNotConfirmedError(RuntimeError):
    """Raised when seed confirmation fails — wrong phrase, stale fingerprint,
    or unknown plan — so nothing executes without a valid review (SEED gate)."""


def discover() -> SeedPlan:
    """Connect read-only to omega, infer schemas, persist a proposed plan."""
    settings = get_platform_settings()
    registry = load_registry()
    mappings = load_type_mappings()
    with oracle_connection() as connection:
        evidence = verify_read_only(connection)
        plan = build_seed_plan(
            connection,
            registry,
            mappings,
            oracle_host=settings.OMEGA_ORACLE_HOST,
            oracle_service=settings.OMEGA_ORACLE_SERVICE_NAME
            or settings.OMEGA_ORACLE_SID,
            read_only_evidence={
                "session_privilege_count": len(evidence["session_privileges"])
            },
        )
    _persist(plan)
    _write_generated_artifacts(plan)
    return plan


def _persist(plan: SeedPlan) -> None:
    engine = loader_engine()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE control.seed_plans SET status = 'superseded' "
                "WHERE status = 'proposed'"
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO control.seed_plans
                    (plan_id, fingerprint, created_at, status, plan)
                VALUES (:plan_id, :fingerprint, :created_at, 'proposed',
                        CAST(:plan AS jsonb))
                ON CONFLICT (plan_id) DO UPDATE
                    SET plan = EXCLUDED.plan,
                        fingerprint = EXCLUDED.fingerprint,
                        status = 'proposed'
                """
            ),
            {
                "plan_id": plan.plan_id,
                "fingerprint": plan.fingerprint(),
                "created_at": plan.created_at,
                "plan": plan.model_dump_json(),
            },
        )


def _write_generated_artifacts(plan: SeedPlan) -> None:
    """Reviewable artifacts under config/generated/ (git-ignored)."""
    settings = get_platform_settings()
    out_dir = settings.generated_config_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "source_catalog.json").write_text(
        plan.model_dump_json(indent=2), encoding="utf-8"
    )
    ddl = "\n\n".join(t.postgres_ddl for t in plan.tables if t.columns)
    (out_dir / "inferred_postgres_raw_ddl.sql").write_text(ddl + "\n", encoding="utf-8")
    logger.info("generated artifacts written to %s", out_dir)


def latest_plan() -> SeedPlan | None:
    engine = loader_engine()
    with engine.connect() as connection:
        row = connection.execute(
            sa.text(
                """
                SELECT plan FROM control.seed_plans
                 WHERE status IN ('proposed', 'confirmed')
                 ORDER BY created_at DESC LIMIT 1
                """
            )
        ).fetchone()
    if row is None:
        return None
    payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    return SeedPlan.model_validate(payload)


def plan_status(plan_id: str) -> str | None:
    engine = loader_engine()
    with engine.connect() as connection:
        return connection.execute(
            sa.text("SELECT status FROM control.seed_plans WHERE plan_id = :p"),
            {"p": plan_id},
        ).scalar()


def confirm_plan(
    plan_id: str,
    fingerprint: str,
    confirmation_phrase: str,
    confirmed_by: str,
) -> SeedPlan:
    """Mark a proposed plan as confirmed; validates phrase + fingerprint."""
    settings = get_platform_settings()
    if (
        settings.SEED_REQUIRE_CONFIRMATION
        and confirmation_phrase != CONFIRMATION_PHRASE
    ):
        raise PlanNotConfirmedError(
            f"Confirmation phrase mismatch. Type {CONFIRMATION_PHRASE!r} to "
            "authorize seeding."
        )
    engine = loader_engine()
    with engine.begin() as connection:
        row = connection.execute(
            sa.text(
                "SELECT fingerprint, status, plan FROM control.seed_plans "
                "WHERE plan_id = :p"
            ),
            {"p": plan_id},
        ).fetchone()
        if row is None:
            raise PlanNotConfirmedError(f"Unknown seed plan {plan_id!r}")
        stored_fingerprint, status, payload = row[0], row[1], row[2]
        if status == "executed":
            raise PlanNotConfirmedError(f"Plan {plan_id} was already executed")
        if stored_fingerprint != fingerprint:
            raise PlanNotConfirmedError(
                "Plan fingerprint mismatch — the plan changed since it was "
                "reviewed. Re-run discovery and review again."
            )
        plan = SeedPlan.model_validate(
            payload if isinstance(payload, dict) else json.loads(payload)
        )
        if not plan.is_seedable:
            raise PlanNotConfirmedError(
                "Plan has blocking issues and cannot be seeded: "
                + "; ".join(plan.blocking_issues[:5])
            )
        connection.execute(
            sa.text(
                """
                UPDATE control.seed_plans
                   SET status = 'confirmed', confirmed_by = :by, confirmed_at = :at
                 WHERE plan_id = :p
                """
            ),
            {"p": plan_id, "by": confirmed_by, "at": dt.datetime.now(dt.timezone.utc)},
        )
    logger.info("seed plan %s confirmed by %s", plan_id, confirmed_by)
    return plan


def mark_executed(plan_id: str, result: dict[str, Any]) -> None:
    engine = loader_engine()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                UPDATE control.seed_plans
                   SET status = 'executed',
                       plan = plan || CAST(:result AS jsonb)
                 WHERE plan_id = :p
                """
            ),
            {"p": plan_id, "result": json.dumps({"execution_result": result})},
        )
