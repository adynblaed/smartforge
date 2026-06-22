"""Factory Intelligence APIs: vision inspection, OEE, trends, recommendations,
machine configuration (spec §6 Factory Intelligence APIs, Module 2)."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import desc, select

from app.api.deps import InternalUser, SessionDep
from app.models import (
    Defect,
    DefectsPublic,
    Factory,
    Incident,
    Inspection,
    InspectionCreate,
    InspectionPublic,
    InspectionsPublic,
    MachineConfiguration,
    MachineConfigurationCreate,
    MachineConfigurationPublic,
    MachineConfigurationsPublic,
    OeeMetric,
    OeeMetricsPublic,
    ProductionRun,
    ProductionRunsPublic,
    Recommendation,
    RecommendationPublic,
    RecommendationsPublic,
    RecommendationStatus,
    Severity,
)
from app.services import factory_intelligence as fi
from app.services.common import list_and_count, write_audit

router = APIRouter(tags=["factory-intelligence"])


# ---- 2A Vision inspection ----
@router.post("/inspection-results", response_model=InspectionPublic)
def submit_inspection(
    payload: InspectionCreate, session: SessionDep, _user: InternalUser
) -> Any:
    data = payload.model_dump()
    if not data.get("defect_type") and not data.get("defect_detected"):
        detected, dtype, conf = fi.vision_verdict(payload.part_id)
        data.update(defect_detected=detected, defect_type=dtype, confidence=conf)
    insp = Inspection(**data)
    session.add(insp)
    session.commit()
    session.refresh(insp)
    if insp.defect_detected:
        session.add(Defect(
            inspection_id=insp.id, line_id=insp.line_id,
            defect_type=insp.defect_type or "unknown", part_id=insp.part_id,
            scrap_cost=fi.SCRAP_UNIT_COST, is_scrap=True,
        ))
        session.commit()
    return insp


@router.get("/inspections", response_model=InspectionsPublic)
def read_inspections(session: SessionDep, _user: InternalUser, limit: int = 100) -> Any:
    rows, count = list_and_count(
        session, Inspection, limit=limit, order_by=desc(Inspection.created_at)
    )
    return InspectionsPublic(data=rows, count=count)


@router.get("/defects", response_model=DefectsPublic)
def read_defects(session: SessionDep, _user: InternalUser, limit: int = 100) -> Any:
    rows, count = list_and_count(
        session, Defect, limit=limit, order_by=desc(Defect.created_at)
    )
    return DefectsPublic(data=rows, count=count)


@router.post("/defects/{defect_id}/correlate")
def correlate_defect(
    defect_id: uuid.UUID, session: SessionDep, user: InternalUser
) -> Any:
    """Tie a quality defect into the incident + ticket ecosystem: create-or-get a
    linked incident and its maintenance ticket (idempotent)."""
    from app.api.routes.tickets import ticket_from_incident

    defect = session.get(Defect, defect_id)
    if not defect:
        raise HTTPException(status_code=404, detail="Defect not found")
    title = (
        f"Quality defect — {defect.defect_type or 'unknown'} "
        f"({defect.part_id or 'n/a'})"
    )
    incident = session.exec(select(Incident).where(Incident.title == title)).first()
    if not incident:
        factory = session.exec(select(Factory)).first()
        if not factory:
            raise HTTPException(status_code=400, detail="No factory configured")
        incident = Incident(
            title=title,
            factory_id=factory.id,
            severity=Severity.high if defect.is_scrap else Severity.medium,
            estimated_cost=defect.scrap_cost or 0.0,
        )
        session.add(incident)
        session.commit()
        session.refresh(incident)
        write_audit(session, actor=user, action="defect.correlate",
                    entity_type="incident", entity_id=incident.id)
    ticket = ticket_from_incident(incident.id, session, user)
    return {
        "incident_id": str(incident.id),
        "incident_title": incident.title,
        "ticket_id": str(ticket.id),
        "ticket_code": ticket.code,
    }


# ---- 2B OEE & production trends ----
@router.get("/oee", response_model=OeeMetricsPublic)
def read_oee(session: SessionDep, _user: InternalUser, limit: int = 200) -> Any:
    rows, count = list_and_count(
        session, OeeMetric, limit=limit, order_by=desc(OeeMetric.created_at)
    )
    return OeeMetricsPublic(data=rows, count=count)


@router.get("/production-trends", response_model=ProductionRunsPublic)
def read_trends(session: SessionDep, _user: InternalUser, limit: int = 200) -> Any:
    rows, count = list_and_count(
        session, ProductionRun, limit=limit, order_by=desc(ProductionRun.created_at)
    )
    return ProductionRunsPublic(data=rows, count=count)


# ---- 2C Machine configuration ----
@router.get("/machine-configurations", response_model=MachineConfigurationsPublic)
def read_configs(session: SessionDep, _user: InternalUser) -> Any:
    rows = list(session.exec(select(MachineConfiguration)).all())
    return MachineConfigurationsPublic(data=rows, count=len(rows))


@router.post("/machine-configurations", response_model=MachineConfigurationPublic)
def create_config(
    payload: MachineConfigurationCreate, session: SessionDep, _user: InternalUser
) -> Any:
    prior = session.exec(
        select(MachineConfiguration)
        .where(MachineConfiguration.machine_id == payload.machine_id)
        .order_by(desc(MachineConfiguration.version))
    ).first()
    cfg = MachineConfiguration.model_validate(
        payload, update={"version": (prior.version + 1) if prior else 1}
    )
    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    return cfg


@router.post(
    "/machine-configurations/{config_id}/approve",
    response_model=MachineConfigurationPublic,
)
def approve_config(
    config_id: uuid.UUID, session: SessionDep, user: InternalUser
) -> Any:
    cfg = session.get(MachineConfiguration, config_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Configuration not found")
    cfg.approved = True
    cfg.is_current = True
    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    write_audit(session, actor=user, action="machine_config.approve",
                entity_type="machine_configuration", entity_id=cfg.id)
    return cfg


# ---- 2D Recommendations (closed-loop) ----
@router.get("/recommendations", response_model=RecommendationsPublic)
def read_recommendations(session: SessionDep, _user: InternalUser) -> Any:
    rows = list(session.exec(
        select(Recommendation).order_by(desc(Recommendation.created_at))
    ).all())
    return RecommendationsPublic(data=rows, count=len(rows))


@router.post("/recommendations/{rec_id}/decision", response_model=RecommendationPublic)
def decide_recommendation(
    rec_id: uuid.UUID, session: SessionDep, user: InternalUser,
    accept: bool, outcome_impact: float | None = None,
) -> Any:
    rec = session.get(Recommendation, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    rec.status = RecommendationStatus.accepted if accept else RecommendationStatus.rejected
    rec.outcome_impact = outcome_impact
    # Closed-loop: nudge confidence by the recorded outcome.
    if accept and outcome_impact is not None:
        rec.confidence = round(min(1.0, rec.confidence + 0.1), 2)
    elif not accept:
        rec.confidence = round(max(0.0, rec.confidence - 0.1), 2)
    session.add(rec)
    session.commit()
    session.refresh(rec)
    write_audit(session, actor=user, action=f"recommendation.{rec.status.value}",
                entity_type="recommendation", entity_id=rec.id)
    return rec
