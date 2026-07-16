"""What-if scheduling & capacity planning APIs (spec §3C)."""

from typing import Any

from fastapi import APIRouter
from sqlmodel import select

from app.api.deps import InternalUser, SessionDep
from app.models import Job, JobStatus, Machine, MachineStatus

router = APIRouter(prefix="/planning", tags=["planning"])


@router.get("/capacity")
def capacity(session: SessionDep, _user: InternalUser) -> Any:
    machines = list(session.exec(select(Machine)).all())
    available = [
        m for m in machines if m.status in (MachineStatus.running, MachineStatus.idle)
    ]
    in_maintenance = [m for m in machines if m.status == MachineStatus.maintenance]
    return {
        "total_machines": len(machines),
        "available": len(available),
        "in_maintenance": len(in_maintenance),
        "maintenance_windows": [
            {"machine": m.code, "state": m.maintenance_state.value}
            for m in machines
            if m.maintenance_state.value != "ok"
        ],
    }


@router.post("/simulate")
def simulate(session: SessionDep, _user: InternalUser) -> Any:
    """What-if: schedule open jobs against available machines; surface conflicts."""
    jobs = list(
        session.exec(
            select(Job).where(
                Job.status.in_(  # type: ignore[attr-defined]
                    [JobStatus.approved, JobStatus.scheduled]
                )
            )
        ).all()
    )
    machines = list(
        session.exec(
            select(Machine).where(Machine.status != MachineStatus.offline)
        ).all()
    )
    capacity_units = max(1, len(machines)) * 1000  # nominal units/window
    demand = sum(j.quantity for j in jobs)
    proposed = []
    for idx, job in enumerate(sorted(jobs, key=lambda j: j.priority)):
        machine = machines[idx % len(machines)] if machines else None
        proposed.append(
            {
                "job": job.part_type,
                "quantity": job.quantity,
                "assigned_machine": machine.code if machine else None,
                "priority": job.priority,
            }
        )
    conflicts = []
    if demand > capacity_units:
        conflicts.append(
            f"Demand {demand} exceeds capacity {capacity_units} this window"
        )
    return {
        "proposed_schedule": proposed,
        "capacity_units": capacity_units,
        "demand_units": demand,
        "capacity_conflicts": conflicts,
        "load_balancing": "Distribute high-priority jobs across available machines",
    }
